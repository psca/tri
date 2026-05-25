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


class RaceStateView(BaseModel):
    race_id: str
    phase: str
    athletes: list[AthleteView]
    accepted_events: list[AcceptedEventView]
    warnings: list[str]
