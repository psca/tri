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


def test_runtime_shutdown_closes_event_store(tmp_path) -> None:
    settings = ServiceSettings.for_tests()
    runtime = RaceRuntime.create(settings, database_path=tmp_path / "race.sqlite")

    runtime.shutdown()

    with pytest.raises(sqlite3.ProgrammingError):
        runtime.state()
