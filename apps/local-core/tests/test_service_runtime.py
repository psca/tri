import asyncio
import sqlite3
from pathlib import Path

import pytest

from tri_timing_service.settings import ServiceSettings
from tri_timing.store import EventStore
from tri_timing_service.runtime import RaceRuntime


def test_service_settings_defaults_to_fixture_paths() -> None:
    settings = ServiceSettings.for_tests()

    assert settings.race_config_path == Path("tests/fixtures/race.yaml")
    assert settings.athletes_path == Path("tests/fixtures/athletes.csv")
    assert settings.database_path.name == "tri-timing-test.sqlite"
    assert settings.cloud_sync_endpoint is None
    assert settings.cloud_sync_token is None


def test_service_settings_can_disable_cloud_sync() -> None:
    settings = ServiceSettings.for_tests()

    assert settings.cloud_sync_endpoint is None
    assert settings.cloud_sync_token is None


def test_runtime_starts_in_pre_start_phase(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    state = runtime.state()

    assert state.phase == "pre_start"
    assert len(state.athletes) == 2
    assert state.athletes[0].athlete_id == "A001"
    assert state.athletes[0].next_event_id == "run1_lap1_complete"


def test_runtime_start_and_close_are_idempotent(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    first = runtime.start()
    second = runtime.start()
    closed = runtime.close()
    closed_again = runtime.close()

    assert first.phase == "live"
    assert second.phase == "live"
    assert closed.phase == "closed"
    assert closed_again.phase == "closed"


def test_runtime_state_includes_accepted_events_from_store(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    with EventStore(database_path) as store:
        store.append_accepted_route_event(
            race_id="duathlon-demo",
            athlete_id="A001",
            route_event_id="run1_lap1_complete",
            checkpoint_id="gate",
            pass_candidate_id="candidate-1",
            event_time_wall="2026-05-25T10:00:00Z",
            confidence="high",
        )
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=database_path)

    state = runtime.state()

    assert len(state.accepted_events) == 1
    assert state.accepted_events[0].athlete_id == "A001"
    assert state.accepted_events[0].route_event_id == "run1_lap1_complete"


def test_runtime_state_projects_next_event_from_existing_accepted_events(
    tmp_path,
) -> None:
    database_path = tmp_path / "race.sqlite"
    with EventStore(database_path) as store:
        store.append_accepted_route_event(
            race_id="duathlon-demo",
            athlete_id="A001",
            route_event_id="run1_lap1_complete",
            checkpoint_id="gate",
            pass_candidate_id="candidate-1",
            event_time_wall="2026-05-25T10:00:00Z",
            confidence="high",
        )
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=database_path)

    state = runtime.state()

    a001 = next(athlete for athlete in state.athletes if athlete.athlete_id == "A001")
    assert a001.next_event_id == "run1_lap2_complete"


def test_runtime_start_does_not_reset_engine_baseline_while_live(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")
    runtime.start()
    runtime._engine.race_start_sec = 12345

    runtime.start()

    assert runtime._engine.race_start_sec == 12345


def test_runtime_restores_live_phase_after_restart(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    database_path = tmp_path / "race.sqlite"
    runtime = RaceRuntime.create(settings, database_path=database_path)
    runtime.start()
    original_start_sec = runtime._engine.race_start_sec
    runtime.shutdown()

    restarted = RaceRuntime.create(settings, database_path=database_path)
    try:
        assert restarted.state().phase == "live"
        assert restarted._engine.race_start_sec == original_start_sec
    finally:
        restarted.shutdown()


def test_runtime_restores_closed_phase_after_restart(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    database_path = tmp_path / "race.sqlite"
    runtime = RaceRuntime.create(settings, database_path=database_path)
    runtime.start()
    runtime.close()
    runtime.shutdown()

    restarted = RaceRuntime.create(settings, database_path=database_path)
    try:
        assert restarted.state().phase == "closed"
    finally:
        restarted.shutdown()


def test_runtime_start_uses_current_monotonic_time(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    runtime.start()

    assert runtime._engine.race_start_sec is not None
    assert runtime._engine.race_start_sec != 100


def test_runtime_state_includes_recent_raw_detections(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    with EventStore(database_path) as store:
        store.append_raw_detection(
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
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=database_path)

    state = runtime.state()

    assert len(state.raw_detections) == 1
    assert state.raw_detections[0].receiver_id == "laptop-dongle-1"
    assert state.raw_detections[0].rssi == -61


def test_runtime_shutdown_closes_event_store(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    runtime.shutdown()

    with pytest.raises(sqlite3.ProgrammingError):
        runtime.state()


def test_runtime_cloud_sync_returns_zero_when_not_configured(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    uploaded = asyncio.run(runtime.publish_cloud_sync_once())

    assert uploaded == 0


def test_runtime_cloud_sync_uses_configured_publisher(tmp_path, monkeypatch) -> None:
    calls = []

    class FakePublisher:
        def __init__(self, *, store, endpoint, token) -> None:
            calls.append((store, endpoint, token))

        async def publish_once(self):
            return type("PublishResult", (), {"uploaded": 3})()

    settings = ServiceSettings(
        race_config_path=Path("tests/fixtures/race.yaml"),
        athletes_path=Path("tests/fixtures/athletes.csv"),
        database_path=tmp_path / "race.sqlite",
        cloud_sync_endpoint="https://example.test/api/ingest",
        cloud_sync_token="secret",
    )
    runtime = RaceRuntime.create(settings)
    monkeypatch.setattr("tri_timing_service.runtime.SyncPublisher", FakePublisher)

    uploaded = asyncio.run(runtime.publish_cloud_sync_once())

    assert uploaded == 3
    assert calls == [
        (
            runtime._store,
            "https://example.test/api/ingest",
            "secret",
        )
    ]
