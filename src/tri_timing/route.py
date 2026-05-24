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
            events.append(
                RouteEvent(
                    id=segment.out_event_id,
                    kind=RouteEventKind.TRANSITION_OUT,
                    checkpoint_id=segment.checkpoint_id,
                    detection_policy_id=segment.detection_policy_id,
                    segment_id=segment.id,
                    sequence=len(events),
                    min_elapsed_sec=segment.min_transition_sec,
                )
            )
            continue

        if isinstance(segment, SportRouteSegmentConfig):
            next_segment = race.route[index + 1] if index + 1 < len(race.route) else None
            _append_sport_events(events, segment, next_segment)
            continue

        raise TypeError(f"Unsupported route segment: {segment!r}")

    return events


def _append_sport_events(
    events: list[RouteEvent],
    segment: SportRouteSegmentConfig,
    next_segment: object | None,
) -> None:
    for lap_number in range(1, segment.laps):
        events.append(
            RouteEvent(
                id=f"{segment.id}_lap{lap_number}_complete",
                kind=RouteEventKind.LAP,
                checkpoint_id=segment.checkpoint_id,
                detection_policy_id=segment.detection_policy_id,
                segment_id=segment.id,
                sequence=len(events),
                sport=segment.sport,
                lap_number=lap_number,
                min_elapsed_sec=segment.min_lap_elapsed_sec,
            )
        )

    if isinstance(next_segment, TransitionRouteSegmentConfig):
        event_id = next_segment.in_event_id
        kind = RouteEventKind.TRANSITION_IN
    else:
        event_id = "finish"
        kind = RouteEventKind.FINISH

    events.append(
        RouteEvent(
            id=event_id,
            kind=kind,
            checkpoint_id=segment.checkpoint_id,
            detection_policy_id=segment.detection_policy_id,
            segment_id=segment.id,
            sequence=len(events),
            sport=segment.sport,
            lap_number=segment.laps,
            min_elapsed_sec=segment.min_lap_elapsed_sec,
        )
    )
