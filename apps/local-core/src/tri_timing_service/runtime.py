from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.engine import RaceEngine
from tri_timing.route import compile_route
from tri_timing.store import EventStore
from tri_timing_service.models import AcceptedEventView, AthleteView, RaceStateView
from tri_timing_service.settings import ServiceSettings


class RaceRuntime:
    def __init__(self, settings: ServiceSettings, database_path: Path) -> None:
        self._settings = settings
        self._race_config = load_race_config(settings.race_config_path)
        self._athletes = load_athletes(settings.athletes_path)
        self._route = compile_route(self._race_config)
        self._store = EventStore(database_path)
        self._engine = RaceEngine(
            race_id=self._race_config.race_id,
            route_events=self._route,
        )
        for athlete in self._athletes:
            self._engine.add_athlete(athlete.athlete_id)
        self._phase = "pre_start"

    @classmethod
    def create(
        cls,
        settings: ServiceSettings,
        database_path: Path | None = None,
    ) -> "RaceRuntime":
        return cls(settings, database_path or settings.database_path)

    def state(self) -> RaceStateView:
        athletes = []
        for athlete in self._athletes:
            engine_state = self._engine.state_for(athlete.athlete_id)
            next_event = (
                self._route[engine_state.next_route_event_index]
                if engine_state.next_route_event_index < len(self._route)
                else None
            )
            athletes.append(
                AthleteView(
                    athlete_id=athlete.athlete_id,
                    name=athlete.name,
                    bib_number=str(athlete.bib),
                    next_event_id=next_event.id if next_event else None,
                    status=engine_state.status,
                )
            )

        accepted_events = [
            AcceptedEventView(
                athlete_id=row["athlete_id"],
                route_event_id=row["route_event_id"],
                checkpoint_id=row["checkpoint_id"],
                timestamp=row["event_time_wall"],
                confidence=row["confidence"],
            )
            for row in self._store.accepted_route_events()
        ]

        return RaceStateView(
            race_id=self._race_config.race_id,
            phase=self._phase,
            athletes=athletes,
            accepted_events=accepted_events,
            warnings=[],
        )

    def start(self) -> RaceStateView:
        if self._phase != "closed":
            self._phase = "live"
            self._engine.start(
                race_start_sec=100,
                start_grace_sec=self._race_config.start.start_grace_sec,
            )
        return self.state()

    def close(self) -> RaceStateView:
        self._phase = "closed"
        return self.state()
