from pydantic import BaseModel


class AthleteView(BaseModel):
    athlete_id: str
    name: str
    bib_number: str | None
    next_event_id: str | None
    status: str


class AcceptedEventView(BaseModel):
    athlete_id: str
    route_event_id: str
    checkpoint_id: str
    timestamp: str
    confidence: str


class RawDetectionView(BaseModel):
    local_sequence_number: int
    receiver_id: str
    checkpoint_id: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    timestamp_wall: str


class RaceStateView(BaseModel):
    race_id: str
    phase: str
    athletes: list[AthleteView]
    accepted_events: list[AcceptedEventView]
    raw_detections: list[RawDetectionView]
    warnings: list[str]


class SyntheticDetectionRequest(BaseModel):
    athlete_id: str
    checkpoint_id: str
    receiver_id: str = "synthetic"
    rssi: int = -55
    repeat_count: int = 6
    timestamp_sec: float | None = None
