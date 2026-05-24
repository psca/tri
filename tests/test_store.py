from tri_timing.store import EventStore


def test_raw_detection_append_assigns_sequence(tmp_path):
    store = EventStore(tmp_path / "race.db")
    first = store.append_raw_detection(
        race_id="duathlon-demo",
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=2,
        rssi=-61,
        timestamp_wall="2026-05-25T08:00:00+08:00",
        timestamp_monotonic=12.5,
        process_instance_id="proc-1",
    )
    second = store.append_raw_detection(
        race_id="duathlon-demo",
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=2,
        rssi=-60,
        timestamp_wall="2026-05-25T08:00:01+08:00",
        timestamp_monotonic=13.5,
        process_instance_id="proc-1",
    )

    assert first == 1
    assert second == 2
    assert [row["local_sequence_number"] for row in store.raw_detections()] == [1, 2]


def test_append_accepted_event_also_enqueues_sync(tmp_path):
    store = EventStore(tmp_path / "race.db")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-demo",
        athlete_id="A002",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T08:07:00+08:00",
        confidence="high",
    )

    events = store.accepted_route_events()
    outbox = store.sync_outbox()

    assert sequence == 1
    assert events[0]["route_event_id"] == "run1_lap1_complete"
    assert outbox[0]["status"] == "pending"
    assert outbox[0]["idempotency_key"] == "duathlon-demo:1"
