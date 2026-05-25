from __future__ import annotations

from tri_timing.models import (
    AthleteState,
    PassCandidate,
    RacePhase,
    RouteDecision,
    RouteEvent,
    RouteEventKind,
)


class RaceEngine:
    def __init__(self, *, race_id: str, route_events: list[RouteEvent]):
        self.race_id = race_id
        self.route_events = route_events
        self.phase = RacePhase.PRE_START
        self.race_start_sec: float | None = None
        self.start_grace_until_sec: float | None = None
        self._states: dict[str, AthleteState] = {}
        self._processed_candidate_ids: dict[str, set[str]] = {}

    def add_athlete(self, athlete_id: str) -> None:
        self._states[athlete_id] = AthleteState(athlete_id=athlete_id)
        self._processed_candidate_ids[athlete_id] = set()

    def start(self, *, race_start_sec: float, start_grace_sec: int) -> None:
        self.phase = RacePhase.LIVE
        self.race_start_sec = race_start_sec
        self.start_grace_until_sec = race_start_sec + start_grace_sec

    def state_for(self, athlete_id: str) -> AthleteState:
        return self._states[athlete_id]

    def apply_pass(
        self,
        athlete_id: str,
        checkpoint_id: str,
        pass_candidate: PassCandidate,
    ) -> RouteDecision:
        if self.phase != RacePhase.LIVE:
            return RouteDecision("suppressed", "race_not_live", None, None)

        state = self._states.get(athlete_id)
        if state is None:
            return RouteDecision("suppressed", "unknown_athlete", None, None)

        processed_candidate_ids = self._processed_candidate_ids.setdefault(
            athlete_id, set()
        )
        if pass_candidate.candidate_id in processed_candidate_ids:
            return RouteDecision("suppressed", "duplicate_candidate", None, None)

        if (
            self.start_grace_until_sec is not None
            and pass_candidate.peak_time_sec < self.start_grace_until_sec
        ):
            processed_candidate_ids.add(pass_candidate.candidate_id)
            return RouteDecision("suppressed", "start_grace", None, None)

        if state.status == "finished" or state.next_route_event_index >= len(
            self.route_events
        ):
            processed_candidate_ids.add(pass_candidate.candidate_id)
            return RouteDecision("suppressed", "already_finished", None, None)

        expected = self.route_events[state.next_route_event_index]
        if expected.checkpoint_id != checkpoint_id:
            processed_candidate_ids.add(pass_candidate.candidate_id)
            return RouteDecision("suppressed", "wrong_checkpoint", None, None)

        baseline = (
            state.last_event_time_sec
            if state.last_event_time_sec is not None
            else self.race_start_sec
        )
        if (
            baseline is not None
            and pass_candidate.peak_time_sec - baseline < expected.min_elapsed_sec
        ):
            processed_candidate_ids.add(pass_candidate.candidate_id)
            return RouteDecision(
                "suppressed",
                "too_early",
                expected.id,
                pass_candidate.peak_time_sec,
            )

        state.next_route_event_index += 1
        state.last_event_time_sec = pass_candidate.peak_time_sec
        if expected.kind == RouteEventKind.FINISH or expected.kind == "finish":
            state.status = "finished"

        processed_candidate_ids.add(pass_candidate.candidate_id)
        return RouteDecision("accepted", None, expected.id, pass_candidate.peak_time_sec)
