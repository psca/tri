from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from tri_timing.store import EventStore
from tri_timing_service.app import create_app
from tri_timing_service.broadcaster import EventBroadcaster
from tri_timing_service.models import RaceStateView
from tri_timing_service.settings import ServiceSettings


def test_health_endpoint(tmp_path) -> None:
    app = create_app(ServiceSettings.for_tests(), database_path=tmp_path / "race.sqlite")

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


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
