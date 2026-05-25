from __future__ import annotations

import argparse
import json
from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.detector import PassDetector
from tri_timing.engine import RaceEngine
from tri_timing.route import compile_route
from tri_timing.scanner import BeaconObservation, SyntheticScanner


def main() -> None:
    parser = argparse.ArgumentParser(prog="tri-timing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("synthetic-replay")
    replay.add_argument("--race", required=True)
    replay.add_argument("--athletes", required=True)
    replay.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "synthetic-replay":
        synthetic_replay(Path(args.race), Path(args.athletes), Path(args.output))


def synthetic_replay(race_path: Path, athletes_path: Path, output_path: Path) -> None:
    race = load_race_config(race_path)
    athletes = load_athletes(athletes_path)
    route_events = compile_route(race)

    engine = RaceEngine(race_id=race.race_id, route_events=route_events)
    for athlete in athletes:
        engine.add_athlete(athlete.athlete_id)
    engine.start(race_start_sec=100, start_grace_sec=race.start.start_grace_sec)

    athlete = athletes[0]
    observations = [
        BeaconObservation(
            500,
            "2026-05-25T08:07:00+08:00",
            athlete.beacon_uuid,
            athlete.beacon_major,
            athlete.beacon_minor,
            -61,
            "laptop-dongle-1",
            "gate",
        ),
        BeaconObservation(
            501,
            "2026-05-25T08:07:01+08:00",
            athlete.beacon_uuid,
            athlete.beacon_major,
            athlete.beacon_minor,
            -56,
            "laptop-dongle-1",
            "gate",
        ),
        BeaconObservation(
            502,
            "2026-05-25T08:07:02+08:00",
            athlete.beacon_uuid,
            athlete.beacon_major,
            athlete.beacon_minor,
            -59,
            "laptop-dongle-1",
            "gate",
        ),
        BeaconObservation(
            506,
            "2026-05-25T08:07:06+08:00",
            athlete.beacon_uuid,
            athlete.beacon_major,
            athlete.beacon_minor,
            -82,
            "laptop-dongle-1",
            "gate",
        ),
    ]

    scanner = SyntheticScanner(observations)
    detector = PassDetector(race.detection_policies["lap_normal"])
    accepted_events: list[dict[str, object]] = []

    for observation in scanner.observations():
        candidate = detector.observe(
            timestamp_sec=observation.timestamp_sec,
            rssi=observation.rssi,
        )
        if candidate is None:
            continue

        decision = engine.apply_pass(
            athlete.athlete_id,
            observation.checkpoint_id,
            candidate,
        )
        if decision.status == "accepted":
            accepted_events.append(
                {
                    "athlete_id": athlete.athlete_id,
                    "route_event_id": decision.route_event_id,
                    "event_time_sec": decision.event_time_sec,
                }
            )

    output_path.write_text(
        json.dumps({"accepted_events": accepted_events}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"accepted {len(accepted_events)} route event")


if __name__ == "__main__":
    main()
