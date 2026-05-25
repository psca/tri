from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tri_timing_service.app import create_app
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
