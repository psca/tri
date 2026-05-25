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


def live_engine() -> RaceEngine:
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.start(race_start_sec=100, start_grace_sec=90)
    return engine


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


def test_unknown_athlete_after_live_is_suppressed():
    engine = live_engine()

    decision = engine.apply_pass("UNKNOWN", "gate", candidate(500))

    assert decision.status == "suppressed"
    assert decision.reason == "unknown_athlete"
    assert decision.route_event_id is None
    assert decision.event_time_sec is None


def test_duplicate_accepted_candidate_advances_only_once():
    engine = live_engine()
    engine.add_athlete("A001")
    pass_candidate = candidate(500)

    first = engine.apply_pass("A001", "gate", pass_candidate)
    second = engine.apply_pass("A001", "gate", pass_candidate)

    assert first.status == "accepted"
    assert second.status == "suppressed"
    assert second.reason == "duplicate_candidate"
    assert engine.state_for("A001").next_route_event_index == 1


def test_wrong_checkpoint_is_suppressed_and_not_advanced():
    engine = live_engine()
    engine.add_athlete("A001")

    decision = engine.apply_pass("A001", "turnaround", candidate(500))

    assert decision.status == "suppressed"
    assert decision.reason == "wrong_checkpoint"
    assert engine.state_for("A001").next_route_event_index == 0


def test_finish_sets_finished_and_later_pass_is_already_finished():
    engine = live_engine()
    engine.add_athlete("A001")

    for index in range(len(engine.route_events)):
        decision = engine.apply_pass("A001", "gate", candidate(500 + index * 700))

    assert decision.status == "accepted"
    assert decision.route_event_id == "finish"
    assert engine.state_for("A001").status == "finished"

    later = engine.apply_pass("A001", "gate", candidate(10_000))

    assert later.status == "suppressed"
    assert later.reason == "already_finished"
