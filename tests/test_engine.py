from pathlib import Path

from tri_timing.config import load_race_config
from tri_timing.engine import RaceEngine
from tri_timing.models import PassCandidate
from tri_timing.route import compile_route


def candidate(peak_time: float) -> PassCandidate:
    return PassCandidate(
        candidate_id=f"candidate-{peak_time}",
        opened_at_sec=peak_time - 2,
        peak_time_sec=peak_time,
        closed_at_sec=peak_time + 3,
        strongest_rssi=-55,
        packet_count=5,
        confidence="high",
    )


def test_start_grace_blocks_route_advancement():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)

    decision = engine.apply_pass(
        athlete_id="A001",
        checkpoint_id="gate",
        pass_candidate=candidate(150),
    )

    assert decision.status == "suppressed"
    assert decision.reason == "start_grace"
    assert engine.state_for("A001").next_route_event_index == 0


def test_expected_pass_advances_one_route_event():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)

    decision = engine.apply_pass(
        athlete_id="A001",
        checkpoint_id="gate",
        pass_candidate=candidate(500),
    )

    assert decision.status == "accepted"
    assert decision.route_event_id == "run1_lap1_complete"
    assert engine.state_for("A001").next_route_event_index == 1


def test_too_early_lap_is_suppressed_and_not_advanced():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)
    engine.apply_pass("A001", "gate", candidate(500))

    decision = engine.apply_pass("A001", "gate", candidate(700))

    assert decision.status == "suppressed"
    assert decision.reason == "too_early"
    assert engine.state_for("A001").next_route_event_index == 1
