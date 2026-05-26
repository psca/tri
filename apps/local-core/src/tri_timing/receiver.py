from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import httpx

from tri_timing.ibeacon import IBeaconAdvertisement
from tri_timing.models import AthleteConfig, RaceConfig


BeaconKey = tuple[str, int, int]


@dataclass(frozen=True)
class ReceiverUploadDetection:
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    timestamp_wall: str
    timestamp_monotonic: float

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiverObservation(ReceiverUploadDetection):
    receiver_id: str
    checkpoint_id: str
    athlete_id: str


def build_beacon_lookup(athletes: list[AthleteConfig]) -> dict[BeaconKey, AthleteConfig]:
    lookup: dict[BeaconKey, AthleteConfig] = {}
    for athlete in athletes:
        key = (
            athlete.beacon_uuid.lower(),
            athlete.beacon_major,
            athlete.beacon_minor,
        )
        existing = lookup.get(key)
        if existing is not None:
            beacon = f"{key[0]}/{key[1]}/{key[2]}"
            raise ValueError(
                "duplicate beacon assignment "
                f"{beacon}: {existing.athlete_id} and {athlete.athlete_id}"
            )
        lookup[key] = athlete
    return lookup


def checkpoint_for_receiver(race: RaceConfig, receiver_id: str) -> str:
    for receiver in race.receivers:
        if receiver.id == receiver_id:
            return receiver.checkpoint_id
    raise ValueError(f"unknown receiver: {receiver_id}")


def observation_from_ibeacon(
    *,
    beacon: IBeaconAdvertisement,
    rssi: int,
    timestamp_wall: str,
    timestamp_monotonic: float,
    receiver_id: str,
    race: RaceConfig,
    beacon_lookup: dict[BeaconKey, AthleteConfig],
) -> ReceiverObservation | None:
    key = (beacon.uuid.lower(), beacon.major, beacon.minor)
    athlete = beacon_lookup.get(key)
    if athlete is None:
        return None

    return ReceiverObservation(
        beacon_uuid=beacon.uuid.lower(),
        beacon_major=beacon.major,
        beacon_minor=beacon.minor,
        rssi=rssi,
        timestamp_wall=timestamp_wall,
        timestamp_monotonic=timestamp_monotonic,
        receiver_id=receiver_id,
        checkpoint_id=checkpoint_for_receiver(race, receiver_id),
        athlete_id=athlete.athlete_id,
    )


def upload_detection_from_ibeacon(
    *,
    beacon: IBeaconAdvertisement,
    rssi: int,
    timestamp_wall: str,
    timestamp_monotonic: float,
) -> ReceiverUploadDetection:
    return ReceiverUploadDetection(
        beacon_uuid=beacon.uuid.lower(),
        beacon_major=beacon.major,
        beacon_minor=beacon.minor,
        rssi=rssi,
        timestamp_wall=timestamp_wall,
        timestamp_monotonic=timestamp_monotonic,
    )


def write_observations_jsonl(
    path: Path, observations: Sequence[ReceiverUploadDetection]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for observation in observations:
            file.write(json.dumps(observation.to_payload(), separators=(",", ":")))
            file.write("\n")


class ReceiverUploader:
    def __init__(self, service_url: str, client: httpx.Client | None = None) -> None:
        self._service_url = service_url.rstrip("/")
        self._client = client or httpx.Client()

    def upload(
        self, receiver_id: str, observations: Sequence[ReceiverUploadDetection]
    ) -> object:
        response = self._client.post(
            f"{self._service_url}/api/detections",
            json={
                "receiver_id": receiver_id,
                "detections": [
                    observation.to_payload() for observation in observations
                ],
            },
        )
        response.raise_for_status()
        return response.json()
