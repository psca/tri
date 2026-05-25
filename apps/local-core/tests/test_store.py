import hashlib
import sqlite3

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


def test_two_connections_share_canonical_sequence(tmp_path):
    first_store = EventStore(tmp_path / "race.db")
    second_store = EventStore(tmp_path / "race.db")

    try:
        first_sequence = first_store.append_raw_detection(
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
        second_sequence = second_store.append_raw_detection(
            race_id="duathlon-demo",
            receiver_id="laptop-dongle-1",
            checkpoint_id="gate",
            beacon_uuid="11111111-1111-1111-1111-111111111111",
            beacon_major=1,
            beacon_minor=2,
            rssi=-60,
            timestamp_wall="2026-05-25T08:00:01+08:00",
            timestamp_monotonic=13.5,
            process_instance_id="proc-2",
        )

        assert first_sequence == 1
        assert second_sequence == 2
        assert [row["local_sequence_number"] for row in first_store.raw_detections()] == [
            1,
            2,
        ]
    finally:
        first_store.close()
        second_store.close()


def test_sync_outbox_payload_hash_matches_stored_payload_json(tmp_path):
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

    outbox = store.sync_outbox()
    expected_hash = hashlib.sha256(
        outbox[0]["payload_json"].encode("utf-8")
    ).hexdigest()

    assert sequence == 1
    assert outbox[0]["payload_hash"] == expected_hash
    assert outbox[0]["idempotency_key"] == "duathlon-demo:1"
    assert outbox[0]["status"] == "pending"


def test_sync_outbox_rows_can_be_marked_synced(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    pending = store.pending_sync_outbox(limit=10)
    assert [row["local_sequence_number"] for row in pending] == [sequence]

    store.mark_sync_success(sequence, synced_at="2026-05-25T09:00:05+00:00")

    assert store.pending_sync_outbox(limit=10) == []
    row = store.sync_outbox()[0]
    assert row["status"] == "synced"
    assert row["synced_at"] == "2026-05-25T09:00:05+00:00"


def test_context_manager_closes_store(tmp_path):
    with EventStore(tmp_path / "race.db") as store:
        assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    try:
        store.raw_detections()
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError("Expected closed EventStore connection to reject reads")


def test_store_enables_wal_and_foreign_keys(tmp_path):
    store = EventStore(tmp_path / "race.db")

    try:
        journal_mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]

        assert journal_mode == "wal"
        assert foreign_keys == 1
    finally:
        store.close()


def test_store_persists_race_metadata(tmp_path):
    store = EventStore(tmp_path / "race.db")

    store.set_metadata("phase", "live")
    store.set_metadata("race_start_wall", "2026-05-25T08:00:00+00:00")
    store.set_metadata("race_start_sec", "123.45")

    reopened = EventStore(tmp_path / "race.db")
    try:
        assert reopened.metadata("phase") == "live"
        assert reopened.metadata("race_start_wall") == "2026-05-25T08:00:00+00:00"
        assert reopened.metadata("race_start_sec") == "123.45"
    finally:
        store.close()
        reopened.close()
