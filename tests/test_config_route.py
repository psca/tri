from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.route import compile_route


def test_loads_race_and_athletes():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))

    assert race.race_id == "duathlon-demo"
    assert race.start.start_grace_sec == 90
    assert athletes[0].athlete_id == "A001"
    assert athletes[1].beacon_minor == 2


def test_compile_route_expands_laps_and_transitions():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    events = compile_route(race)

    assert [event.id for event in events] == [
        "run1_lap1_complete",
        "run1_lap2_complete",
        "run1_lap3_complete",
        "run1_complete_t1_in",
        "t1_out_bike_start",
        "bike_lap1_complete",
        "bike_lap2_complete",
        "bike_complete_t2_in",
        "t2_out_run2_start",
        "run2_lap1_complete",
        "run2_lap2_complete",
        "run2_lap3_complete",
        "finish",
    ]
    assert events[3].detection_policy_id == "lap_normal"
    assert events[4].detection_policy_id == "transition_strict"
    assert events[-1].kind == "finish"
