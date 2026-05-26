import time
from datetime import UTC, datetime
from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.detector import PassDetector
from tri_timing.engine import RaceEngine
from tri_timing.models import RouteEventKind
from tri_timing.review import ReviewState, build_review_state
from tri_timing.route import compile_route
from tri_timing.store import EventStore
from tri_timing_service.models import (
    AcceptedEventView,
    AthleteView,
    ManualCorrectionRequest,
    RaceStateView,
    RawDetectionView,
    SyntheticDetectionRequest,
)
from tri_timing_service.settings import ServiceSettings
from tri_timing_service.sync import SyncPublisher


ALLOWED_CORRECTION_TYPES = {
    "manual_add_pass",
    "manual_reject_pass",
    "manual_override_time",
    "mark_status",
}
ALLOWED_MANUAL_STATUSES = {"dnf", "dq", "manual_finished", "racing"}


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
        self._hydrate_engine_from_store()
        self._phase = self._store.metadata("phase") or "pre_start"
        self._restore_engine_phase()

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
        raw_detections = [
            RawDetectionView(
                local_sequence_number=row["local_sequence_number"],
                receiver_id=row["receiver_id"],
                checkpoint_id=row["checkpoint_id"],
                beacon_uuid=row["beacon_uuid"],
                beacon_major=row["beacon_major"],
                beacon_minor=row["beacon_minor"],
                rssi=row["rssi"],
                timestamp_wall=row["timestamp_wall"],
            )
            for row in self._store.raw_detections(limit=25)
        ]

        return RaceStateView(
            race_id=self._race_config.race_id,
            phase=self._phase,
            athletes=athletes,
            accepted_events=accepted_events,
            raw_detections=raw_detections,
            warnings=[],
        )

    def review_state(self) -> ReviewState:
        return build_review_state(
            race_id=self._race_config.race_id,
            phase=self._phase,
            athletes=[
                {
                    "athlete_id": athlete.athlete_id,
                    "name": athlete.name,
                    "bib": athlete.bib,
                }
                for athlete in self._athletes
            ],
            route_events=self._route,
            accepted_events=self._store.accepted_route_events(),
            manual_corrections=self._store.manual_corrections(),
            raw_detections=self._store.raw_detections(limit=25),
        )

    def corrections(self) -> list[dict]:
        return self._store.manual_corrections()

    def apply_manual_correction(
        self, request: ManualCorrectionRequest
    ) -> ReviewState:
        if self._phase not in {"live", "closed"}:
            raise ValueError("corrections are only allowed live or closed")

        athlete_ids = {athlete.athlete_id for athlete in self._athletes}
        if request.athlete_id not in athlete_ids:
            raise ValueError(f"unknown athlete: {request.athlete_id}")

        if request.correction_type not in ALLOWED_CORRECTION_TYPES:
            raise ValueError(f"unknown correction type: {request.correction_type}")

        route_event_ids = {event.id for event in self._route}
        if (
            request.route_event_id is not None
            and request.route_event_id not in route_event_ids
        ):
            raise ValueError(f"unknown route event: {request.route_event_id}")

        if not request.reason.strip():
            raise ValueError("reason is required")

        if request.correction_type == "manual_add_pass":
            if request.route_event_id is None:
                raise ValueError("route_event_id is required")
            if request.corrected_time_wall is None:
                raise ValueError("corrected_time_wall is required")

        elif request.correction_type == "manual_reject_pass":
            if request.target_local_sequence_number is None:
                raise ValueError("target_local_sequence_number is required")
            target_sequences = self._targetable_timeline_sequences(request.athlete_id)
            if request.target_local_sequence_number not in target_sequences:
                raise ValueError("target event does not exist")

        elif request.correction_type == "manual_override_time":
            if request.target_local_sequence_number is None:
                raise ValueError("target_local_sequence_number is required")
            if request.corrected_time_wall is None:
                raise ValueError("corrected_time_wall is required")
            target_sequences = self._targetable_timeline_sequences(request.athlete_id)
            if request.target_local_sequence_number not in target_sequences:
                raise ValueError("target event does not exist")

        elif request.correction_type == "mark_status":
            if request.status not in ALLOWED_MANUAL_STATUSES:
                raise ValueError(f"unknown status: {request.status}")

        self._store.append_manual_correction(
            race_id=self._race_config.race_id,
            correction_type=request.correction_type,
            athlete_id=request.athlete_id,
            route_event_id=request.route_event_id,
            target_local_sequence_number=request.target_local_sequence_number,
            corrected_time_wall=request.corrected_time_wall,
            status=request.status,
            reason=request.reason,
            created_at=datetime.now(tz=UTC).isoformat(),
            created_by=request.created_by,
        )
        return self.review_state()

    def _targetable_timeline_sequences(self, athlete_id: str) -> set[int]:
        target_sequences: set[int] = set()
        for athlete in self.review_state().athletes:
            if athlete.athlete_id != athlete_id:
                continue
            for event in athlete.timeline:
                if event.status == "accepted" and event.accepted_local_sequence_number:
                    target_sequences.add(event.accepted_local_sequence_number)
                elif event.status == "manual":
                    target_sequences.update(event.correction_sequence_numbers)
            break
        return target_sequences

    def start(self) -> RaceStateView:
        if self._phase == "pre_start":
            self._phase = "live"
            race_start_sec = time.monotonic()
            race_start_wall = datetime.now(tz=UTC).isoformat()
            self._store.set_metadata("phase", self._phase)
            self._store.set_metadata("race_start_sec", str(race_start_sec))
            self._store.set_metadata("race_start_wall", race_start_wall)
            self._engine.start(
                race_start_sec=race_start_sec,
                start_grace_sec=self._race_config.start.start_grace_sec,
            )
        return self.state()

    def close(self) -> RaceStateView:
        self._phase = "closed"
        self._store.set_metadata("phase", self._phase)
        self._store.set_metadata("race_closed_wall", datetime.now(tz=UTC).isoformat())
        return self.state()

    def synthetic_detection(self, request: SyntheticDetectionRequest) -> RaceStateView:
        athlete = next(
            (
                athlete
                for athlete in self._athletes
                if athlete.athlete_id == request.athlete_id
            ),
            None,
        )
        if athlete is None:
            raise ValueError(f"unknown athlete: {request.athlete_id}")

        checkpoint_ids = {checkpoint.id for checkpoint in self._race_config.checkpoints}
        if request.checkpoint_id not in checkpoint_ids:
            raise ValueError(f"unknown checkpoint: {request.checkpoint_id}")

        if self._phase != "live":
            return self.state()

        engine_state = self._engine.state_for(request.athlete_id)
        if engine_state.next_route_event_index >= len(self._route):
            return self.state()

        expected_event = self._route[engine_state.next_route_event_index]
        policy = self._race_config.detection_policies[
            expected_event.detection_policy_id
        ]
        detector = PassDetector(policy)
        timestamp_sec = request.timestamp_sec
        if timestamp_sec is None:
            baseline = (
                engine_state.last_event_time_sec
                or self._engine.race_start_sec
                or 100
            )
            timestamp_sec = (
                baseline
                + expected_event.min_elapsed_sec
                + self._race_config.start.start_grace_sec
                + 1
            )

        candidate = None
        wall_time = datetime.now(tz=UTC).isoformat()
        samples = [
            (timestamp_sec + index, request.rssi)
            for index in range(request.repeat_count)
        ]
        samples.append(
            (
                timestamp_sec + request.repeat_count + policy.clear_sec,
                policy.close_rssi_threshold,
            )
        )

        for sample_time, rssi in samples:
            self._store.append_raw_detection(
                race_id=self._race_config.race_id,
                receiver_id=request.receiver_id,
                checkpoint_id=request.checkpoint_id,
                beacon_uuid=athlete.beacon_uuid,
                beacon_major=athlete.beacon_major,
                beacon_minor=athlete.beacon_minor,
                rssi=rssi,
                timestamp_wall=wall_time,
                timestamp_monotonic=sample_time,
                process_instance_id="synthetic",
            )
            candidate = (
                detector.observe(timestamp_sec=sample_time, rssi=rssi) or candidate
            )

        if candidate is not None:
            decision = self._engine.apply_pass(
                request.athlete_id,
                request.checkpoint_id,
                candidate,
            )
            if decision.status == "accepted" and decision.route_event_id is not None:
                self._store.append_accepted_route_event(
                    race_id=self._race_config.race_id,
                    athlete_id=request.athlete_id,
                    route_event_id=decision.route_event_id,
                    checkpoint_id=request.checkpoint_id,
                    pass_candidate_id=candidate.candidate_id,
                    event_time_wall=wall_time,
                    confidence=candidate.confidence,
                )

        return self.state()

    def shutdown(self) -> None:
        self._store.close()

    async def publish_cloud_sync_once(self) -> int:
        if (
            self._settings.cloud_sync_endpoint is None
            or self._settings.cloud_sync_token is None
        ):
            return 0

        publisher = SyncPublisher(
            store=self._store,
            endpoint=self._settings.cloud_sync_endpoint,
            token=self._settings.cloud_sync_token,
        )
        result = await publisher.publish_once()
        return result.uploaded

    def _hydrate_engine_from_store(self) -> None:
        for row in self._store.accepted_route_events():
            if row["race_id"] != self._race_config.race_id:
                continue

            try:
                state = self._engine.state_for(row["athlete_id"])
            except KeyError:
                continue

            if state.next_route_event_index >= len(self._route):
                continue

            expected = self._route[state.next_route_event_index]
            if row["route_event_id"] != expected.id:
                continue

            state.next_route_event_index += 1
            event_time_sec = self._peak_time_sec_from_candidate_id(
                row["pass_candidate_id"]
            )
            if event_time_sec is not None:
                state.last_event_time_sec = event_time_sec

            processed_candidate_ids = self._engine._processed_candidate_ids.setdefault(
                row["athlete_id"], set()
            )
            if row["pass_candidate_id"] is not None:
                processed_candidate_ids.add(row["pass_candidate_id"])

            if expected.kind == RouteEventKind.FINISH or expected.kind == "finish":
                state.status = "finished"

    def _restore_engine_phase(self) -> None:
        if self._phase not in {"live", "closed"}:
            return

        race_start_sec_text = self._store.metadata("race_start_sec")
        try:
            race_start_sec = (
                float(race_start_sec_text) if race_start_sec_text is not None else None
            )
        except ValueError:
            race_start_sec = None

        if race_start_sec is not None:
            self._engine.start(
                race_start_sec=race_start_sec,
                start_grace_sec=self._race_config.start.start_grace_sec,
            )

    def _peak_time_sec_from_candidate_id(self, candidate_id: str | None) -> float | None:
        if candidate_id is None:
            return None

        parts = candidate_id.split("-")
        if len(parts) < 4 or parts[0] != "candidate":
            return None

        try:
            return int(parts[2]) / 1000
        except ValueError:
            return None
