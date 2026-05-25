from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RacePhase(StrEnum):
    PRE_START = "pre_start"
    ARMED = "armed"
    LIVE = "live"
    CLOSED = "closed"


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
class DetectionPolicy:
    id: str
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
    detection_policies: dict[str, DetectionPolicy]


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
    candidate_id: str
    opened_at_sec: float
    peak_time_sec: float
    closed_at_sec: float
    strongest_rssi: int
    packet_count: int
    confidence: str


@dataclass(frozen=True)
class RouteEvent:
    index: int
    id: str
    label: str
    checkpoint_id: str
    kind: RouteEventKind
    sport: str | None
    min_elapsed_sec: int
    cooldown_sec: int
    detection_policy_id: str
    manual_allowed: bool = True


@dataclass
class AthleteState:
    athlete_id: str
    next_route_event_index: int = 0
    last_event_time_sec: float | None = None
    status: str = "racing"


@dataclass(frozen=True)
class RouteDecision:
    status: str
    reason: str | None
    route_event_id: str | None
    event_time_sec: float | None
