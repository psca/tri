from __future__ import annotations

import json
import subprocess


def test_synthetic_replay_exports_accepted_events(tmp_path):
    output_path = tmp_path / "result.json"
    command = [
        "uv",
        "run",
        "tri-timing",
        "synthetic-replay",
        "--race",
        "tests/fixtures/race.yaml",
        "--athletes",
        "tests/fixtures/athletes.csv",
        "--output",
        str(output_path),
    ]

    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(output_path.read_text())

    assert "accepted 1 route event" in result.stdout
    assert data["accepted_events"][0]["athlete_id"] == "A001"
    assert data["accepted_events"][0]["route_event_id"] == "run1_lap1_complete"
