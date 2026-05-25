from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class BeaconObservation:
    timestamp_sec: float
    timestamp_wall: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    receiver_id: str
    checkpoint_id: str


class Scanner(Protocol):
    def observations(self) -> Iterable[BeaconObservation]:
        raise NotImplementedError


class SyntheticScanner:
    def __init__(self, observations: list[BeaconObservation]):
        self._observations = observations

    def observations(self) -> Iterable[BeaconObservation]:
        return list(self._observations)
