from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from tri_timing.store import EventStore


@dataclass(frozen=True)
class PublishResult:
    uploaded: int
    failed: int


class SyncPublisher:
    def __init__(
        self,
        *,
        store: EventStore,
        endpoint: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._endpoint = endpoint
        self._token = token
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def publish_once(self, *, limit: int = 10) -> PublishResult:
        rows = self._store.pending_sync_outbox(limit=limit)
        uploaded = 0
        failed = 0

        async with httpx.AsyncClient(transport=self._transport, timeout=5.0) as client:
            for row in rows:
                sequence = int(row["local_sequence_number"])
                try:
                    response = await client.post(
                        self._endpoint,
                        json=self._envelope(row),
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                except httpx.HTTPError as exc:
                    self._store.mark_sync_failure(
                        sequence,
                        error=str(exc),
                        next_attempt_at=self._next_attempt_at(row),
                    )
                    failed += 1
                    continue

                if response.status_code in {200, 201, 202}:
                    self._store.mark_sync_success(
                        sequence,
                        synced_at=self._clock().isoformat(),
                    )
                    uploaded += 1
                    continue

                error = f"HTTP {response.status_code}: {response.text[:200]}"
                if self._is_retryable_status(response.status_code):
                    self._store.mark_sync_failure(
                        sequence,
                        error=error,
                        next_attempt_at=self._next_attempt_at(row),
                    )
                else:
                    self._store.mark_sync_permanent_failure(sequence, error=error)
                failed += 1

        return PublishResult(uploaded=uploaded, failed=failed)

    def _envelope(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(str(row["payload_json"]))
        return {
            "idempotency_key": row["idempotency_key"],
            "payload_hash": row["payload_hash"],
            "race_id": payload["race_id"],
            "local_sequence_number": row["local_sequence_number"],
            "type": payload["type"],
            "created_at": self._clock().isoformat(),
            "payload": payload,
        }

    def _next_attempt_at(self, row: dict[str, Any]) -> str:
        attempts = int(row["attempts"])
        delay = timedelta(seconds=60 * (2**attempts))
        return (self._clock() + delay).isoformat()

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code in {408, 425, 429} or 500 <= status_code <= 599
