from pathlib import Path
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from tri_timing.store import EventStore
from tri_timing_service.app import create_app
from tri_timing_service.broadcaster import EventBroadcaster
from tri_timing_service.models import RaceStateView
from tri_timing_service.runtime import RaceRuntime
from tri_timing_service.settings import ServiceSettings


def test_health_endpoint(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_create_app_uses_env_settings_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRI_RACE_CONFIG", "tests/fixtures/race.yaml")
    monkeypatch.setenv("TRI_ATHLETES", "tests/fixtures/athletes.csv")
    monkeypatch.setenv("TRI_DATABASE", str(tmp_path / "env-race.sqlite"))

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/race/state")

    assert response.status_code == 200
    assert response.json()["race_id"] == "duathlon-demo"


def test_lifespan_runs_cloud_sync_loop(tmp_path, monkeypatch) -> None:
    calls = 0

    class FakeRuntime:
        @classmethod
        def create(cls, settings, database_path=None):
            return cls()

        def state(self):
            return RaceStateView(
                race_id="duathlon-demo",
                phase="pre_start",
                athletes=[],
                accepted_events=[],
                raw_detections=[],
                warnings=[],
            )

        async def publish_cloud_sync_once(self):
            nonlocal calls
            calls += 1
            return 0

        def shutdown(self):
            pass

    monkeypatch.setattr("tri_timing_service.app.RaceRuntime", FakeRuntime)
    settings = ServiceSettings(
        race_config_path=Path("tests/fixtures/race.yaml"),
        athletes_path=Path("tests/fixtures/athletes.csv"),
        database_path=tmp_path / "race.sqlite",
        cloud_sync_interval_sec=0.01,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/race/state")
        assert response.status_code == 200
        asyncio.run(asyncio.sleep(0.03))

    assert calls > 0


def test_lifespan_fails_startup_when_config_missing(tmp_path) -> None:
    settings = ServiceSettings(
        race_config_path=Path("tests/fixtures/missing-race.yaml"),
        athletes_path=Path("tests/fixtures/missing-athletes.csv"),
        database_path=tmp_path / "race.sqlite",
    )
    app = create_app(settings)

    with pytest.raises(FileNotFoundError):
        with TestClient(app):
            pass


def test_state_start_and_close_endpoints(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        initial = client.get("/api/race/state").json()
        started = client.post("/api/race/start").json()
        closed = client.post("/api/race/close").json()

    assert initial["phase"] == "pre_start"
    assert started["phase"] == "live"
    assert closed["phase"] == "closed"


def test_reentering_same_app_recreates_runtime_after_lifespan_shutdown(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/race/state")
        assert response.status_code == 200

    with TestClient(app) as client:
        response = client.get("/api/race/state")
        assert response.status_code == 200


def test_synthetic_detection_advances_expected_event(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_events"][0]["route_event_id"] == "run1_lap1_complete"
    assert body["athletes"][0]["next_event_id"] == "run1_lap2_complete"


def test_restart_hydrates_last_event_time_for_too_early_detection(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    app = create_app(ServiceSettings.for_tests(), database_path=database_path)

    with TestClient(app) as client:
        client.post("/api/race/start")
        first = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert first.status_code == 200
    assert first.json()["athletes"][0]["next_event_id"] == "run1_lap2_complete"

    with EventStore(database_path) as store:
        first_peak_time = store.raw_detections()[0]["timestamp_monotonic"]

    with TestClient(app) as client:
        second = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
                "timestamp_sec": first_peak_time + 10,
            },
        )

    assert second.status_code == 200
    body = second.json()
    assert [event["route_event_id"] for event in body["accepted_events"]] == [
        "run1_lap1_complete"
    ]
    assert body["athletes"][0]["next_event_id"] == "run1_lap2_complete"


def test_restart_default_synthetic_timestamp_uses_last_event_time(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    app = create_app(ServiceSettings.for_tests(), database_path=database_path)

    with TestClient(app) as client:
        client.post("/api/race/start")
        first = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert first.status_code == 200

    with TestClient(app) as client:
        client.post("/api/race/start")
        second = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert second.status_code == 200
    body = second.json()
    assert [event["route_event_id"] for event in body["accepted_events"]] == [
        "run1_lap1_complete",
        "run1_lap2_complete",
    ]

    with EventStore(database_path) as store:
        raw_detections = store.raw_detections()

    first_detection_samples = raw_detections[:7]
    second_detection_samples = raw_detections[7:]
    assert second_detection_samples[0]["timestamp_monotonic"] == pytest.approx(
        first_detection_samples[0]["timestamp_monotonic"] + 360 + 90 + 1
    )


def test_synthetic_detection_unknown_athlete_returns_400(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "UNKNOWN",
                "checkpoint_id": "gate",
                "timestamp_sec": 500,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown athlete: UNKNOWN"


def test_sse_stream_sends_initial_state(tmp_path, monkeypatch) -> None:
    class FakeBroadcaster:
        def stream(self, initial_state: RaceStateView):
            return iter(
                [
                    "event: connected\ndata: {}\n\n",
                    f"event: state\ndata: {initial_state.model_dump_json()}\n\n",
                ]
            )

        def publish_state(self, state: RaceStateView) -> None:
            pass

    monkeypatch.setattr("tri_timing_service.app.EventBroadcaster", FakeBroadcaster)
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/events/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: connected" in response.text
    state_line = response.text.split("event: state\n", maxsplit=1)[1].splitlines()[0]

    payload = json.loads(state_line.removeprefix("data: "))
    assert payload["phase"] == "pre_start"


def test_app_publishes_state_after_start(tmp_path, monkeypatch) -> None:
    class FakeBroadcaster:
        published: list[RaceStateView] = []

        def stream(self, initial_state: RaceStateView):
            return iter(())

        def publish_state(self, state: RaceStateView) -> None:
            self.published.append(state)

    fake = FakeBroadcaster()
    monkeypatch.setattr("tri_timing_service.app.EventBroadcaster", lambda: fake)
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post("/api/race/start")

    assert response.status_code == 200
    assert fake.published[-1].phase == "live"


def test_sse_stream_publishes_state_to_subscribers(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")
    with TestClient(app) as client:
        started_state = RaceStateView.model_validate(client.post("/api/race/start").json())

    broadcaster = EventBroadcaster()
    stream = broadcaster.stream(started_state)
    assert next(stream) == "event: connected\ndata: {}\n\n"
    assert json.loads(next(stream).splitlines()[1].removeprefix("data: "))[
        "phase"
    ] == "live"

    broadcaster.publish_state(started_state)
    state_line = next(stream).splitlines()[1]

    payload = json.loads(state_line.removeprefix("data: "))
    assert payload["phase"] == "live"


def test_review_state_endpoint_returns_timelines(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/review/state")

    assert response.status_code == 200
    body = response.json()
    assert body["race_id"] == "duathlon-demo"
    assert body["athletes"][0]["timeline"]


def test_post_correction_adds_manual_pass_and_publishes_review_and_race_state(
    tmp_path, monkeypatch
) -> None:
    class FakeBroadcaster:
        published_states: list[RaceStateView] = []
        published_reviews: list[object] = []

        def stream(self, initial_state: RaceStateView):
            return iter(())

        def publish_state(self, state: RaceStateView) -> None:
            self.published_states.append(state)

        def publish_review(self, review) -> None:
            self.published_reviews.append(review)

    fake = FakeBroadcaster()
    monkeypatch.setattr("tri_timing_service.app.EventBroadcaster", lambda: fake)
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Saw athlete cross while BLE missed",
                "created_by": "operator",
            },
        )
        review = client.get("/api/review/state").json()

    assert response.status_code == 200
    assert review["athletes"][0]["timeline"][0]["status"] == "manual"
    assert fake.published_reviews
    assert fake.published_states[-1].athletes[0].next_event_id == "run1_lap2_complete"


def test_restart_hydrates_manual_add_pass_progression(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    app = create_app(ServiceSettings.for_tests(), database_path=database_path)

    with TestClient(app) as client:
        client.post("/api/race/start")
        manual = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Saw athlete cross while BLE missed",
                "created_by": "operator",
            },
        )

    assert manual.status_code == 200

    with TestClient(app) as client:
        restarted_state = client.get("/api/race/state").json()
        detected = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert restarted_state["athletes"][0]["next_event_id"] == "run1_lap2_complete"
    assert detected.status_code == 200
    assert [event["route_event_id"] for event in detected.json()["accepted_events"]] == [
        "run1_lap2_complete"
    ]
    assert detected.json()["athletes"][0]["next_event_id"] == "run1_lap3_complete"


def test_post_correction_rejects_unknown_athlete(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "UNKNOWN",
                "status": "dnf",
                "reason": "No such athlete",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400


def test_post_correction_rejects_when_race_not_live_or_closed(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "status": "dnf",
                "reason": "Stopped before start",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "corrections are only allowed live or closed"


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (
            {
                "correction_type": "unknown",
                "athlete_id": "A001",
                "reason": "Bad type",
            },
            "unknown correction type: unknown",
        ),
        (
            {
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Missing route event",
            },
            "route_event_id is required",
        ),
        (
            {
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "reason": "Missing corrected time",
            },
            "corrected_time_wall is required",
        ),
        (
            {
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "reason": "Missing target",
            },
            "target_local_sequence_number is required",
        ),
        (
            {
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": 1,
                "reason": "Missing corrected time",
            },
            "corrected_time_wall is required",
        ),
        (
            {
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "status": "finished",
                "reason": "Bad status",
            },
            "unknown status: finished",
        ),
    ],
)
def test_post_correction_rejects_invalid_shapes(
    tmp_path, payload: dict[str, object], detail: str
) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post("/api/corrections", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_corrections_endpoint_returns_correction_log(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "status": "dnf",
                "reason": "Stopped after bike",
                "created_by": "operator",
            },
        )
        response = client.get("/api/corrections")

    assert response.status_code == 200
    corrections = response.json()["corrections"]
    assert corrections[0]["correction_type"] == "mark_status"
    assert corrections[0]["reason"] == "Stopped after bike"


def test_post_correction_rejects_unknown_route_event(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "unknown_event",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Saw athlete cross while BLE missed",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown route event: unknown_event"


def test_post_correction_rejects_blank_reason(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "status": "dnf",
                "reason": "   ",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "reason is required"


def test_post_correction_rejects_omitted_reason_as_bad_request(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "mark_status",
                "athlete_id": "A001",
                "status": "dnf",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "reason is required"


def test_post_correction_rejects_missing_target_event(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": 999,
                "reason": "False positive",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "target event does not exist"


def test_post_correction_accepts_overridden_event_as_target(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )
        review = client.get("/api/review/state").json()
        target_sequence = review["athletes"][0]["timeline"][0][
            "accepted_local_sequence_number"
        ]

        first_override = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": target_sequence,
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Use camera time",
                "created_by": "operator",
            },
        )
        first_override_timeline = first_override.json()["athletes"][0]["timeline"][0]
        override_sequence = first_override_timeline["correction_sequence_numbers"][0]

        second_override = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": target_sequence,
                "corrected_time_wall": "2026-05-25T09:11:00+08:00",
                "reason": "Refine camera time",
                "created_by": "operator",
            },
        )
        reject_override = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": override_sequence,
                "reason": "Camera showed wrong athlete",
                "created_by": "operator",
            },
        )

    assert first_override.status_code == 200
    assert second_override.status_code == 200
    assert reject_override.status_code == 200


def test_post_correction_accepts_rejected_event_as_target(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )
        review = client.get("/api/review/state").json()
        target_sequence = review["athletes"][0]["timeline"][0][
            "accepted_local_sequence_number"
        ]

        reject = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": target_sequence,
                "reason": "Rejected wrong pass by mistake",
                "created_by": "operator",
            },
        )
        override_rejected = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_override_time",
                "athlete_id": "A001",
                "target_local_sequence_number": target_sequence,
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Restore with camera time",
                "created_by": "operator",
            },
        )

    assert reject.status_code == 200
    assert override_rejected.status_code == 200
    assert (
        override_rejected.json()["athletes"][0]["timeline"][0]["status"]
        == "overridden"
    )


def test_manual_add_pass_syncs_live_engine_next_event(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        manual = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_add_pass",
                "athlete_id": "A001",
                "route_event_id": "run1_lap1_complete",
                "corrected_time_wall": "2026-05-25T09:10:00+08:00",
                "reason": "Saw athlete cross while BLE missed",
                "created_by": "operator",
            },
        )
        state_after_manual = client.get("/api/race/state").json()
        detected = client.post(
            "/api/synthetic/detection",
            json={
                "athlete_id": "A001",
                "checkpoint_id": "gate",
                "receiver_id": "synthetic",
                "rssi": -55,
                "repeat_count": 6,
            },
        )

    assert manual.status_code == 200
    assert state_after_manual["athletes"][0]["next_event_id"] == "run1_lap2_complete"
    assert detected.status_code == 200
    assert [event["route_event_id"] for event in detected.json()["accepted_events"]] == [
        "run1_lap2_complete"
    ]
    assert detected.json()["athletes"][0]["next_event_id"] == "run1_lap3_complete"


def test_post_correction_rejects_target_from_invalid_raw_manual_add(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    with EventStore(database_path) as store:
        stale_target_sequence = store.append_manual_correction(
            race_id="duathlon-demo",
            correction_type="manual_add_pass",
            athlete_id="A001",
            route_event_id="unknown_event",
            target_local_sequence_number=None,
            corrected_time_wall="2026-05-25T09:10:00+08:00",
            status=None,
            reason="Legacy invalid row",
            created_at="2026-05-25T09:11:00+08:00",
            created_by="operator",
        )

    app = create_app(ServiceSettings.for_tests(), database_path=database_path)

    with TestClient(app) as client:
        client.post("/api/race/start")
        response = client.post(
            "/api/corrections",
            json={
                "correction_type": "manual_reject_pass",
                "athlete_id": "A001",
                "target_local_sequence_number": stale_target_sequence,
                "reason": "Reject invalid legacy row",
                "created_by": "operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "target event does not exist"


def _detection_payload(
    *, minor: int = 1, rssi: int = -55, timestamp_sec: float = 500
):
    return {
        "receiver_id": "laptop-dongle-1",
        "detections": [
            {
                "beacon_uuid": "11111111-1111-1111-1111-111111111111",
                "beacon_major": 1,
                "beacon_minor": minor,
                "rssi": rssi,
                "timestamp_wall": "2026-05-26T09:00:00+08:00",
                "timestamp_monotonic": timestamp_sec,
            }
        ],
    }


def test_runtime_rejects_duplicate_beacon_assignments(tmp_path) -> None:
    athletes_path = tmp_path / "athletes.csv"
    athletes_path.write_text(
        "\n".join(
            [
                "athlete_id,bib,name,beacon_uuid,beacon_major,beacon_minor",
                "A001,1,Alice,11111111-1111-1111-1111-111111111111,1,1",
                "A999,999,Imposter,11111111-1111-1111-1111-111111111111,1,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = ServiceSettings(
        race_config_path=Path("tests/fixtures/race.yaml"),
        athletes_path=athletes_path,
        database_path=tmp_path / "race.sqlite",
    )

    with pytest.raises(ValueError, match="duplicate beacon assignment"):
        RaceRuntime(settings, tmp_path / "race.sqlite")


def test_detection_ingest_stores_known_raw_detection(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post("/api/detections", json=_detection_payload())
        state = client.get("/api/race/state").json()

    assert response.status_code == 200
    assert response.json()["stored"] == 1
    assert state["raw_detections"][0]["receiver_id"] == "laptop-dongle-1"
    assert state["raw_detections"][0]["checkpoint_id"] == "gate"


def test_detection_ingest_advances_live_race_after_candidate_closes(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/race/start")
        for offset, rssi in [(500, -55), (501, -54), (502, -53), (506, -83)]:
            response = client.post(
                "/api/detections",
                json=_detection_payload(rssi=rssi, timestamp_sec=offset),
            )
        state = client.get("/api/race/state").json()

    assert response.status_code == 200
    assert response.json()["accepted_events"][0]["route_event_id"] == (
        "run1_lap1_complete"
    )
    assert state["athletes"][0]["next_event_id"] == "run1_lap2_complete"


def test_detection_ingest_accepted_event_uses_peak_packet_wall_time(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    app = create_app(ServiceSettings.for_tests(), database_path=database_path)
    samples = [
        (500, -60, "2026-05-26T09:00:00+08:00"),
        (501, -50, "2026-05-26T09:00:01+08:00"),
        (502, -55, "2026-05-26T09:00:02+08:00"),
        (506, -83, "2026-05-26T09:00:06+08:00"),
    ]

    with TestClient(app) as client:
        client.post("/api/race/start")
        for timestamp_sec, rssi, timestamp_wall in samples:
            payload = _detection_payload(rssi=rssi, timestamp_sec=timestamp_sec)
            payload["detections"][0]["timestamp_wall"] = timestamp_wall
            response = client.post("/api/detections", json=payload)

    assert response.status_code == 200
    assert response.json()["accepted_events"][0]["route_event_id"] == (
        "run1_lap1_complete"
    )
    with EventStore(database_path) as store:
        accepted = store.accepted_route_events()

    assert accepted[0]["event_time_wall"] == "2026-05-26T09:00:01+08:00"


def test_detection_ingest_restart_hydrates_partial_detector_state(tmp_path) -> None:
    database_path = tmp_path / "race.sqlite"
    app = create_app(ServiceSettings.for_tests(), database_path=database_path)

    with TestClient(app) as client:
        client.post("/api/race/start")
        for offset, rssi in [(500, -55), (501, -54), (502, -53)]:
            response = client.post(
                "/api/detections",
                json=_detection_payload(rssi=rssi, timestamp_sec=offset),
            )

    assert response.status_code == 200
    assert response.json()["accepted_events"] == []

    with TestClient(app) as client:
        response = client.post(
            "/api/detections",
            json=_detection_payload(rssi=-83, timestamp_sec=506),
        )

    assert response.status_code == 200
    assert response.json()["accepted_events"][0]["route_event_id"] == (
        "run1_lap1_complete"
    )


def test_detection_ingest_rejects_unknown_receiver(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        payload = _detection_payload()
        payload["receiver_id"] = "unknown"
        response = client.post("/api/detections", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown receiver: unknown"


def test_detection_ingest_counts_unknown_beacon_without_raw_detection(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.post("/api/detections", json=_detection_payload(minor=99))
        health = client.get("/api/receivers/health").json()
        state = client.get("/api/race/state").json()

    assert response.status_code == 200
    assert response.json()["stored"] == 0
    assert response.json()["ignored_unknown"] == 1
    assert state["raw_detections"] == []
    assert health["receivers"][0]["unknown_packets"] == 1


def test_receiver_health_reports_online_receiver(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/detections", json=_detection_payload())
        response = client.get("/api/receivers/health")

    assert response.status_code == 200
    receiver = response.json()["receivers"][0]
    assert receiver["receiver_id"] == "laptop-dongle-1"
    assert receiver["checkpoint_id"] == "gate"
    assert receiver["status"] == "online"
    assert receiver["known_packets"] == 1
    assert receiver["latest_known_beacons"][0]["athlete_id"] == "A001"


def test_receiver_health_reports_stale_receiver_without_sleeping(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        client.post("/api/detections", json=_detection_payload(timestamp_sec=100))
        health = app.state.runtime.receiver_health(now_monotonic=200)

    assert health.receivers[0].status == "silent"
