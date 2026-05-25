import asyncio
import json

import httpx

from tri_timing.store import EventStore
from tri_timing_service.sync import SyncPublisher


def test_sync_publisher_marks_success(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.path == "/api/ingest"
        data = json.loads(request.content)
        assert data["idempotency_key"] == f"duathlon-001:{sequence}"
        assert data["payload_hash"] == store.sync_outbox()[0]["payload_hash"]
        assert data["race_id"] == "duathlon-001"
        assert data["local_sequence_number"] == sequence
        assert data["type"] == "accepted_route_event"
        assert data["created_at"]
        assert data["payload"]["athlete_id"] == "A001"
        return httpx.Response(202, json={"status": "accepted"})

    publisher = SyncPublisher(
        store=store,
        endpoint="https://example.test/api/ingest",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(publisher.publish_once())

    assert result.uploaded == 1
    assert result.failed == 0
    assert store.pending_sync_outbox(limit=10) == []


def test_sync_publisher_marks_retryable_failure(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    publisher = SyncPublisher(
        store=store,
        endpoint="https://example.test/api/ingest",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(publisher.publish_once())

    assert result.uploaded == 0
    assert result.failed == 1
    row = store.sync_outbox()[0]
    assert row["local_sequence_number"] == sequence
    assert row["status"] == "failed_retryable"
    assert row["attempts"] == 1
    assert row["last_error"].startswith("HTTP 503:")
