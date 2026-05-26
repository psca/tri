from tri_timing.models import RouteEvent, RouteEventKind
from tri_timing.review import build_review_state


ROUTE = [
    RouteEvent(
        index=0,
        id="run1_lap1_complete",
        label="Run 1 Lap 1",
        checkpoint_id="gate",
        kind=RouteEventKind.LAP,
        sport="run",
        min_elapsed_sec=0,
        cooldown_sec=45,
        detection_policy_id="normal",
    ),
    RouteEvent(
        index=1,
        id="finish",
        label="Finish",
        checkpoint_id="gate",
        kind=RouteEventKind.FINISH,
        sport="run",
        min_elapsed_sec=0,
        cooldown_sec=45,
        detection_policy_id="strict",
    ),
]

ATHLETES = [
    {"athlete_id": "A001", "name": "Bob", "bib": 12},
    {"athlete_id": "A002", "name": "Mei", "bib": 7},
]


def test_review_projection_marks_missing_and_accepted_events() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            }
        ],
        manual_corrections=[],
        raw_detections=[],
    )

    bob = review.athletes[0]
    mei = review.athletes[1]
    assert bob.timeline[0].status == "accepted"
    assert bob.timeline[1].status == "missing"
    assert mei.attention_level == "needs_attention"


def test_review_projection_applies_manual_add_reject_override_and_status() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            }
        ],
        manual_corrections=[
            {
                "local_sequence_number": 6,
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": 5,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": None,
                "reason": "False positive",
                "created_at": "2026-05-25T09:11:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 7,
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": "finish",
                "corrected_time_wall": "2026-05-25T09:40:00+08:00",
                "status": None,
                "reason": "Saw finish",
                "created_at": "2026-05-25T09:41:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 8,
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": "manual_finished",
                "reason": "Manual finish accepted",
                "created_at": "2026-05-25T09:42:00+08:00",
                "created_by": "operator",
            },
        ],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert bob.status == "manual_finished"
    assert bob.timeline[0].status == "rejected"
    assert bob.timeline[1].status == "manual"
    assert bob.timeline[1].source == "manual"


def test_review_projection_applies_corrections_by_sequence_order() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            }
        ],
        manual_corrections=[
            {
                "local_sequence_number": 8,
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": 5,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": None,
                "reason": "Reject after override",
                "created_at": "2026-05-25T09:14:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 7,
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": 5,
                "route_event_id": None,
                "corrected_time_wall": "2026-05-25T09:12:00+08:00",
                "status": None,
                "reason": "Use camera time",
                "created_at": "2026-05-25T09:13:00+08:00",
                "created_by": "operator",
            },
        ],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert bob.timeline[0].status == "rejected"
    assert bob.timeline[0].timestamp == "2026-05-25T09:12:00+08:00"
    assert bob.timeline[0].original_timestamp == "2026-05-25T09:10:00+08:00"
    assert bob.timeline[0].correction_sequence_numbers == [7, 8]


def test_review_projection_warns_for_invalid_or_stale_corrections() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[],
        manual_corrections=[
            {
                "local_sequence_number": 3,
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": "unknown",
                "corrected_time_wall": "2026-05-25T09:12:00+08:00",
                "status": None,
                "reason": "Bad route event",
                "created_at": "2026-05-25T09:13:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 4,
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": 999,
                "route_event_id": None,
                "corrected_time_wall": "2026-05-25T09:12:00+08:00",
                "status": None,
                "reason": "Missing accepted event",
                "created_at": "2026-05-25T09:13:00+08:00",
                "created_by": "operator",
            },
        ],
        raw_detections=[],
    )

    assert len(review.warnings) == 2
    assert review.athletes[0].timeline[0].status == "missing"


def test_review_projection_overrides_manual_add_by_target_sequence() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[],
        manual_corrections=[
            {
                "local_sequence_number": 7,
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": "finish",
                "corrected_time_wall": "2026-05-25T09:40:00+08:00",
                "status": None,
                "reason": "Saw finish",
                "created_at": "2026-05-25T09:41:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 8,
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": 7,
                "route_event_id": None,
                "corrected_time_wall": "2026-05-25T09:42:00+08:00",
                "status": None,
                "reason": "Use camera time",
                "created_at": "2026-05-25T09:43:00+08:00",
                "created_by": "operator",
            },
        ],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert bob.timeline[1].status == "overridden"
    assert bob.timeline[1].source == "override"
    assert bob.timeline[1].timestamp == "2026-05-25T09:42:00+08:00"
    assert bob.timeline[1].original_timestamp == "2026-05-25T09:40:00+08:00"
    assert bob.timeline[1].correction_sequence_numbers == [7, 8]


def test_review_projection_keeps_lowest_sequence_duplicate_accepted_event() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[
            {
                "local_sequence_number": 9,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:12:00+08:00",
                "confidence": "medium",
            },
            {
                "local_sequence_number": 5,
                "race_id": "duathlon-demo",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "checkpoint_id": "gate",
                "event_time_wall": "2026-05-25T09:10:00+08:00",
                "confidence": "high",
            },
        ],
        manual_corrections=[],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert bob.timeline[0].accepted_local_sequence_number == 5
    assert bob.timeline[0].timestamp == "2026-05-25T09:10:00+08:00"
    assert bob.timeline[0].confidence == "high"
    assert review.warnings == ["ignored duplicate accepted event 9: run1_lap1_complete"]


def test_review_projection_warns_for_correction_without_sequence() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[],
        manual_corrections=[
            {
                "local_sequence_number": None,
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": "dns",
                "reason": "Invalid row",
                "created_at": "2026-05-25T09:13:00+08:00",
                "created_by": "operator",
            },
            {
                "local_sequence_number": 4,
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": None,
                "corrected_time_wall": None,
                "status": "manual_finished",
                "reason": "Valid row",
                "created_at": "2026-05-25T09:14:00+08:00",
                "created_by": "operator",
            }
        ],
        raw_detections=[],
    )

    assert review.warnings == ["ignored correction without local sequence number"]
    assert review.athletes[0].status == "manual_finished"


def test_review_projection_warns_for_manual_add_without_corrected_time() -> None:
    review = build_review_state(
        race_id="duathlon-demo",
        phase="live",
        athletes=ATHLETES,
        route_events=ROUTE,
        accepted_events=[],
        manual_corrections=[
            {
                "local_sequence_number": 7,
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": None,
                "route_event_id": "finish",
                "corrected_time_wall": None,
                "status": None,
                "reason": "Missing time",
                "created_at": "2026-05-25T09:41:00+08:00",
                "created_by": "operator",
            }
        ],
        raw_detections=[],
    )

    bob = review.athletes[0]
    assert review.warnings == ["ignored correction 7: missing corrected time"]
    assert bob.timeline[1].status == "missing"
    assert bob.timeline[1].timestamp is None
