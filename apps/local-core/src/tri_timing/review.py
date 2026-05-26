from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tri_timing.models import RouteEvent


class ReviewTimelineEvent(BaseModel):
    route_event_id: str
    label: str
    status: str
    timestamp: str | None
    confidence: str | None
    source: str
    accepted_local_sequence_number: int | None = None
    original_timestamp: str | None = None
    correction_sequence_numbers: list[int] = Field(default_factory=list)


class ReviewAthlete(BaseModel):
    athlete_id: str
    name: str
    bib_number: str | None
    status: str
    next_event_id: str | None
    completed_count: int
    total_count: int
    attention_level: str
    badges: list[str] = Field(default_factory=list)
    timeline: list[ReviewTimelineEvent] = Field(default_factory=list)


class ReviewState(BaseModel):
    race_id: str
    phase: str
    route_events: list[dict[str, str | int | None]] = Field(default_factory=list)
    athletes: list[ReviewAthlete] = Field(default_factory=list)
    correction_log: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_detections: list[dict[str, Any]] = Field(default_factory=list)


def build_review_state(
    *,
    race_id: str,
    phase: str,
    athletes: list[dict[str, Any]],
    route_events: list[RouteEvent],
    accepted_events: list[dict[str, Any]],
    manual_corrections: list[dict[str, Any]],
    raw_detections: list[dict[str, Any]],
) -> ReviewState:
    warnings: list[str] = []
    athlete_ids = {athlete["athlete_id"] for athlete in athletes}
    route_event_ids = {event.id for event in route_events}
    accepted_by_sequence: dict[int, dict[str, Any]] = {}
    event_states: dict[tuple[str, str], ReviewTimelineEvent] = {}

    for accepted in accepted_events:
        if accepted.get("race_id", race_id) != race_id:
            continue
        sequence = _sequence_number(accepted)
        if sequence is None:
            warnings.append("ignored accepted event without local sequence number")
            continue
        key = (accepted["athlete_id"], accepted["route_event_id"])
        if key in event_states:
            warnings.append(
                f"ignored duplicate accepted event {sequence}: {accepted['route_event_id']}"
            )
            continue
        accepted_by_sequence[sequence] = accepted
        event_states[key] = ReviewTimelineEvent(
            route_event_id=accepted["route_event_id"],
            label="",
            status="accepted",
            timestamp=accepted.get("event_time_wall"),
            confidence=accepted.get("confidence"),
            source="ble",
            accepted_local_sequence_number=sequence,
        )

    status_by_athlete = {athlete_id: "racing" for athlete_id in athlete_ids}
    sorted_corrections = sorted(
        manual_corrections, key=lambda correction: correction.get("local_sequence_number", 0)
    )
    for correction in sorted_corrections:
        sequence = _sequence_number(correction)
        if sequence is None:
            warnings.append("ignored correction without local sequence number")
            continue
        if correction.get("race_id", race_id) != race_id:
            warnings.append(f"ignored correction {sequence}: wrong race")
            continue
        athlete_id = correction.get("athlete_id")
        if athlete_id not in athlete_ids:
            warnings.append(f"ignored correction {sequence}: unknown athlete")
            continue

        correction_type = correction.get("correction_type")
        if correction_type == "manual_add_pass":
            _apply_manual_add_pass(
                correction=correction,
                event_states=event_states,
                route_event_ids=route_event_ids,
                warnings=warnings,
            )
        elif correction_type == "manual_reject_pass":
            _apply_targeted_correction(
                correction=correction,
                accepted_by_sequence=accepted_by_sequence,
                event_states=event_states,
                status="rejected",
                source="ble",
                warnings=warnings,
            )
        elif correction_type == "manual_override_time":
            _apply_manual_override_time(
                correction=correction,
                accepted_by_sequence=accepted_by_sequence,
                event_states=event_states,
                warnings=warnings,
            )
        elif correction_type == "mark_status":
            status = correction.get("status")
            if status:
                status_by_athlete[athlete_id] = status
            else:
                warnings.append(f"ignored correction {sequence}: missing status")
        else:
            warnings.append(f"ignored correction {sequence}: unknown type {correction_type}")

    review_athletes = _build_review_athletes(
        athletes=athletes,
        route_events=route_events,
        event_states=event_states,
        status_by_athlete=status_by_athlete,
    )
    review_athletes.sort(
        key=lambda athlete: (
            athlete.attention_level != "needs_attention",
            athlete.name,
            athlete.athlete_id,
        )
    )

    return ReviewState(
        race_id=race_id,
        phase=phase,
        route_events=[
            {
                "index": event.index,
                "id": event.id,
                "label": event.label,
                "checkpoint_id": event.checkpoint_id,
                "kind": event.kind,
                "sport": event.sport,
            }
            for event in route_events
        ],
        athletes=review_athletes,
        correction_log=manual_corrections,
        warnings=warnings,
        raw_detections=raw_detections,
    )


def _apply_manual_add_pass(
    *,
    correction: dict[str, Any],
    event_states: dict[tuple[str, str], ReviewTimelineEvent],
    route_event_ids: set[str],
    warnings: list[str],
) -> None:
    sequence = int(correction["local_sequence_number"])
    route_event_id = correction.get("route_event_id")
    if route_event_id not in route_event_ids:
        warnings.append(f"ignored correction {sequence}: unknown route event")
        return
    key = (correction["athlete_id"], route_event_id)
    existing = event_states.get(key)
    if existing is not None and existing.status != "missing":
        warnings.append(f"ignored correction {sequence}: route event already has a pass")
        return
    event_states[key] = ReviewTimelineEvent(
        route_event_id=route_event_id,
        label="",
        status="manual",
        timestamp=correction.get("corrected_time_wall"),
        confidence=None,
        source="manual",
        correction_sequence_numbers=[sequence],
    )


def _apply_targeted_correction(
    *,
    correction: dict[str, Any],
    accepted_by_sequence: dict[int, dict[str, Any]],
    event_states: dict[tuple[str, str], ReviewTimelineEvent],
    status: str,
    source: str,
    warnings: list[str],
) -> None:
    sequence = int(correction["local_sequence_number"])
    target = _target_state(
        correction=correction,
        accepted_by_sequence=accepted_by_sequence,
        event_states=event_states,
        warnings=warnings,
    )
    if target is None:
        return
    target.status = status
    target.source = source
    target.correction_sequence_numbers.append(sequence)


def _apply_manual_override_time(
    *,
    correction: dict[str, Any],
    accepted_by_sequence: dict[int, dict[str, Any]],
    event_states: dict[tuple[str, str], ReviewTimelineEvent],
    warnings: list[str],
) -> None:
    sequence = int(correction["local_sequence_number"])
    target = _target_state(
        correction=correction,
        accepted_by_sequence=accepted_by_sequence,
        event_states=event_states,
        warnings=warnings,
    )
    if target is None:
        return
    if correction.get("corrected_time_wall") is None:
        warnings.append(f"ignored correction {sequence}: missing corrected time")
        return
    if target.original_timestamp is None:
        target.original_timestamp = target.timestamp
    target.timestamp = correction["corrected_time_wall"]
    target.status = "overridden"
    target.source = "override"
    target.correction_sequence_numbers.append(sequence)


def _target_state(
    *,
    correction: dict[str, Any],
    accepted_by_sequence: dict[int, dict[str, Any]],
    event_states: dict[tuple[str, str], ReviewTimelineEvent],
    warnings: list[str],
) -> ReviewTimelineEvent | None:
    sequence = int(correction["local_sequence_number"])
    target_sequence = correction.get("target_local_sequence_number")
    if target_sequence is None:
        warnings.append(f"ignored correction {sequence}: missing target")
        return None
    accepted = accepted_by_sequence.get(int(target_sequence))
    if accepted is None:
        warnings.append(f"ignored correction {sequence}: stale target")
        return None
    if accepted["athlete_id"] != correction["athlete_id"]:
        warnings.append(f"ignored correction {sequence}: target athlete mismatch")
        return None
    return event_states.get((accepted["athlete_id"], accepted["route_event_id"]))


def _build_review_athletes(
    *,
    athletes: list[dict[str, Any]],
    route_events: list[RouteEvent],
    event_states: dict[tuple[str, str], ReviewTimelineEvent],
    status_by_athlete: dict[str, str],
) -> list[ReviewAthlete]:
    review_athletes: list[ReviewAthlete] = []
    for athlete in athletes:
        timeline: list[ReviewTimelineEvent] = []
        badges: set[str] = set()
        completed = 0
        next_event_id: str | None = None
        athlete_id = athlete["athlete_id"]

        for route_event in route_events:
            event = event_states.get((athlete_id, route_event.id))
            if event is None:
                if next_event_id is None:
                    next_event_id = route_event.id
                badges.add("missing")
                timeline.append(
                    ReviewTimelineEvent(
                        route_event_id=route_event.id,
                        label=route_event.label,
                        status="missing",
                        timestamp=None,
                        confidence=None,
                        source="none",
                    )
                )
                continue

            event.label = route_event.label
            timeline.append(event)
            if event.status in {"accepted", "manual", "overridden"}:
                completed += 1
            elif next_event_id is None:
                next_event_id = route_event.id
            if event.status != "accepted":
                badges.add(event.status)

        attention_level = (
            "needs_attention"
            if any(event.status in {"missing", "rejected"} for event in timeline)
            else "ok"
        )
        review_athletes.append(
            ReviewAthlete(
                athlete_id=athlete_id,
                name=athlete["name"],
                bib_number=(
                    str(athlete["bib"])
                    if athlete.get("bib") is not None
                    else athlete.get("bib_number")
                ),
                status=status_by_athlete.get(athlete_id, "racing"),
                next_event_id=next_event_id,
                completed_count=completed,
                total_count=len(route_events),
                attention_level=attention_level,
                badges=sorted(badges),
                timeline=timeline,
            )
        )
    return review_athletes


def _sequence_number(row: dict[str, Any]) -> int | None:
    value = row.get("local_sequence_number")
    if value is None:
        return None
    return int(value)
