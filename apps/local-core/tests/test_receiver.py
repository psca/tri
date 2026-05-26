from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from tri_timing.config import load_athletes, load_race_config
from tri_timing.ibeacon import IBeaconAdvertisement
from tri_timing.models import AthleteConfig
from tri_timing.receiver import (
    ReceiverObservation,
    ReceiverUploader,
    build_beacon_lookup,
    observation_from_ibeacon,
    write_observations_jsonl,
)


def test_build_beacon_lookup_maps_configured_athletes() -> None:
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))

    lookup = build_beacon_lookup(athletes)

    assert lookup[("11111111-1111-1111-1111-111111111111", 1, 1)].athlete_id == "A001"
    assert lookup[("11111111-1111-1111-1111-111111111111", 1, 2)].athlete_id == "A002"


def test_build_beacon_lookup_rejects_duplicate_beacon_assignments() -> None:
    athletes = [
        AthleteConfig(
            athlete_id="A001",
            bib=1,
            name="Ada",
            beacon_uuid="11111111-1111-1111-1111-111111111111",
            beacon_major=1,
            beacon_minor=1,
        ),
        AthleteConfig(
            athlete_id="A002",
            bib=2,
            name="Bea",
            beacon_uuid="11111111-1111-1111-1111-111111111111",
            beacon_major=1,
            beacon_minor=1,
        ),
    ]

    with pytest.raises(ValueError) as error:
        build_beacon_lookup(athletes)

    message = str(error.value)
    assert "duplicate beacon assignment" in message
    assert "11111111-1111-1111-1111-111111111111/1/1" in message
    assert "A001" in message
    assert "A002" in message


def test_observation_from_ibeacon_filters_unknown_beacons() -> None:
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))
    lookup = build_beacon_lookup(athletes)

    known = observation_from_ibeacon(
        beacon=IBeaconAdvertisement(
            uuid="11111111-1111-1111-1111-111111111111",
            major=1,
            minor=1,
            measured_power=-59,
        ),
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
        receiver_id="laptop-dongle-1",
        race=race,
        beacon_lookup=lookup,
    )
    unknown = observation_from_ibeacon(
        beacon=IBeaconAdvertisement(
            uuid="22222222-2222-2222-2222-222222222222",
            major=1,
            minor=1,
            measured_power=-59,
        ),
        rssi=-70,
        timestamp_wall="2026-05-26T09:00:01+08:00",
        timestamp_monotonic=101.5,
        receiver_id="laptop-dongle-1",
        race=race,
        beacon_lookup=lookup,
    )

    assert known is not None
    assert known.athlete_id == "A001"
    assert known.checkpoint_id == "gate"
    assert unknown is None


def test_write_observations_jsonl_appends_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "receiver" / "observations.jsonl"
    observation = ReceiverObservation(
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        athlete_id="A001",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=1,
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
    )

    write_observations_jsonl(path, [observation])
    write_observations_jsonl(path, [observation])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        observation.to_payload(),
        observation.to_payload(),
    ]


def test_receiver_uploader_posts_detections_and_returns_json() -> None:
    observation = ReceiverObservation(
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        athlete_id="A001",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=1,
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"accepted": 1})

    uploader = ReceiverUploader(
        "http://local.test/",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = uploader.upload("laptop-dongle-1", [observation])

    assert result == {"accepted": 1}
    assert requests[0].url == "http://local.test/api/detections"
    assert json.loads(requests[0].content) == {
        "receiver_id": "laptop-dongle-1",
        "detections": [observation.to_payload()],
    }


def test_receiver_uploader_raises_http_status_error_on_server_error() -> None:
    observation = ReceiverObservation(
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        athlete_id="A001",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=1,
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
    )
    uploader = ReceiverUploader(
        "http://local.test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, request=request)
            )
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        uploader.upload("laptop-dongle-1", [observation])


def test_receiver_command_is_registered() -> None:
    result = subprocess.run(
        ["uv", "run", "tri-timing", "receiver-run", "--help"],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--receiver-id" in result.stdout
    assert "--service-url" in result.stdout
    assert "--jsonl-log" in result.stdout
