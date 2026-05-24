from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StartMode(StrEnum):
    MASS_BUTTON = "mass_button"


class RouteSegmentKind(StrEnum):
    SPORT = "sport"
    TRANSITION = "transition"


class RouteEventKind(StrEnum):
    LAP = "lap"
    TRANSITION_IN = "transition_in"
    TRANSITION_OUT = "transition_out"
    FINISH = "finish"


class DetectionDecision(StrEnum):
    ACCEPT = "accept"
    SUPPRESS = "suppress"
    IGNORE = "ignore"


@dataclass(frozen=True)
class RaceStartConfig:
    mode: StartMode
    checkpoint_id: str
    start_grace_sec: int


@dataclass(frozen=True)
class CheckpointConfig:
    id: str
    name: str


@dataclass(frozen=True)
class ReceiverConfig:
    id: str
    checkpoint_id: str


@dataclass(frozen=True)
class DetectionPolicyConfig:
    strong_rssi_threshold: int
    close_rssi_threshold: int
    min_packets: int
    window_sec: int
    clear_sec: int
    cooldown_sec: int


@dataclass(frozen=True)
class SportRouteSegmentConfig:
    id: str
    sport: str
    checkpoint_id: str
    laps: int
    min_lap_elapsed_sec: int
    detection_policy_id: str
    kind: RouteSegmentKind = RouteSegmentKind.SPORT


@dataclass(frozen=True)
class TransitionRouteSegmentConfig:
    id: str
    in_event_id: str
    out_event_id: str
    checkpoint_id: str
    min_transition_sec: int
    detection_policy_id: str
    kind: RouteSegmentKind = RouteSegmentKind.TRANSITION


RouteSegmentConfig = SportRouteSegmentConfig | TransitionRouteSegmentConfig


@dataclass(frozen=True)
class RaceConfig:
    race_id: str
    name: str
    start: RaceStartConfig
    checkpoints: list[CheckpointConfig]
    receivers: list[ReceiverConfig]
    route: list[RouteSegmentConfig]
    detection_policies: dict[str, DetectionPolicyConfig]


@dataclass(frozen=True)
class AthleteConfig:
    athlete_id: str
    bib: int
    name: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int


@dataclass(frozen=True)
class BleDetection:
    athlete_id: str | None
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    receiver_id: str
    checkpoint_id: str
    rssi: int
    detected_at_ms: int


@dataclass(frozen=True)
class PassCandidate:
    athlete_id: str
    checkpoint_id: str
    first_seen_ms: int
    last_seen_ms: int
    packet_count: int
    strongest_rssi: int
    detection_policy_id: str


@dataclass(frozen=True)
class RouteEvent:
    id: str
    kind: RouteEventKind
    checkpoint_id: str
    detection_policy_id: str
    segment_id: str
    sequence: int
    sport: str | None = None
    lap_number: int | None = None
    min_elapsed_sec: int | None = None
