from __future__ import annotations

from tri_timing.models import (
    RaceConfig,
    RouteEvent,
    RouteEventKind,
    SportRouteSegmentConfig,
    TransitionRouteSegmentConfig,
)


def compile_route(race: RaceConfig) -> list[RouteEvent]:
    events: list[RouteEvent] = []

    for index, segment in enumerate(race.route):
        if isinstance(segment, TransitionRouteSegmentConfig):
            policy = _get_detection_policy(race, segment.id, segment.detection_policy_id)
            events.append(
                RouteEvent(
                    index=len(events),
                    id=segment.out_event_id,
                    label=f"{segment.id} out",
                    checkpoint_id=segment.checkpoint_id,
                    kind=RouteEventKind.TRANSITION_OUT,
                    sport=None,
                    min_elapsed_sec=segment.min_transition_sec,
                    cooldown_sec=policy.cooldown_sec,
                    detection_policy_id=segment.detection_policy_id,
                )
            )
            continue

        if isinstance(segment, SportRouteSegmentConfig):
            next_segment = race.route[index + 1] if index + 1 < len(race.route) else None
            _append_sport_events(race, events, segment, next_segment)
            continue

        raise TypeError(f"Unsupported route segment: {segment!r}")

    return events


def _append_sport_events(
    race: RaceConfig,
    events: list[RouteEvent],
    segment: SportRouteSegmentConfig,
    next_segment: object | None,
) -> None:
    for lap_number in range(1, segment.laps):
        policy = _get_detection_policy(race, segment.id, segment.detection_policy_id)
        events.append(
            RouteEvent(
                index=len(events),
                id=f"{segment.id}_lap{lap_number}_complete",
                label=f"{segment.id} lap {lap_number} complete",
                checkpoint_id=segment.checkpoint_id,
                kind=RouteEventKind.LAP,
                sport=segment.sport,
                min_elapsed_sec=segment.min_lap_elapsed_sec,
                cooldown_sec=policy.cooldown_sec,
                detection_policy_id=segment.detection_policy_id,
            )
        )

    if isinstance(next_segment, TransitionRouteSegmentConfig):
        event_id = next_segment.in_event_id
        kind = RouteEventKind.TRANSITION_IN
        label = f"{segment.id} complete / {next_segment.id} in"
    else:
        event_id = "finish"
        kind = RouteEventKind.FINISH
        label = "Finish"

    policy = _get_detection_policy(race, segment.id, segment.detection_policy_id)
    events.append(
        RouteEvent(
            index=len(events),
            id=event_id,
            label=label,
            checkpoint_id=segment.checkpoint_id,
            kind=kind,
            sport=segment.sport,
            min_elapsed_sec=segment.min_lap_elapsed_sec,
            cooldown_sec=policy.cooldown_sec,
            detection_policy_id=segment.detection_policy_id,
        )
    )


def _get_detection_policy(race: RaceConfig, segment_id: str, policy_id: str):
    try:
        return race.detection_policies[policy_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown detection policy '{policy_id}' for route segment '{segment_id}'"
        ) from exc
