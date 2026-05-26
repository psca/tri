from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Sequence

from bleak import BleakScanner

from tri_timing.config import load_athletes, load_race_config
from tri_timing.ibeacon import parse_ibeacon_manufacturer_data
from tri_timing.models import RaceConfig
from tri_timing.receiver import (
    ReceiverUploadDetection,
    ReceiverUploader,
    build_beacon_lookup,
    checkpoint_for_receiver,
    upload_detection_from_ibeacon,
    write_observations_jsonl,
)


class _ObservationUploader(Protocol):
    def upload(
        self, receiver_id: str, observations: Sequence[ReceiverUploadDetection]
    ) -> object: ...


class _PendingObservationQueue:
    def __init__(self) -> None:
        self._observations: list[ReceiverUploadDetection] = []
        self._persisted_count = 0

    def __len__(self) -> int:
        return len(self._observations)

    def append(self, observation: ReceiverUploadDetection) -> None:
        self._observations.append(observation)

    def flush_to_jsonl(self, path: Path) -> None:
        if self._persisted_count >= len(self._observations):
            return
        write_observations_jsonl(path, self._observations[self._persisted_count :])
        self._persisted_count = len(self._observations)

    def drop_oldest_for_upload(self, max_observations: int) -> int:
        if max_observations < 1:
            raise ValueError("max_pending_observations must be at least 1")
        drop_count = len(self._observations) - max_observations
        if drop_count <= 0:
            return 0

        del self._observations[:drop_count]
        self._persisted_count = max(0, self._persisted_count - drop_count)
        return drop_count

    def upload_snapshot(self) -> list[ReceiverUploadDetection]:
        return list(self._observations)

    def mark_uploaded(self, uploaded_count: int) -> None:
        if uploaded_count <= 0:
            return
        del self._observations[:uploaded_count]
        self._persisted_count = max(0, self._persisted_count - uploaded_count)


def _persist_and_bound_pending(
    *,
    queue: _PendingObservationQueue,
    jsonl_log: Path,
    max_pending_observations: int,
) -> None:
    queue.flush_to_jsonl(jsonl_log)
    dropped_count = queue.drop_oldest_for_upload(max_pending_observations)
    if dropped_count:
        print(
            "receiver upload backlog exceeded "
            f"{max_pending_observations}; dropped {dropped_count} oldest pending "
            "BLE observations from upload backlog after JSONL persistence",
            file=sys.stderr,
        )


async def _flush_and_upload_pending(
    *,
    queue: _PendingObservationQueue,
    jsonl_log: Path,
    uploader: _ObservationUploader,
    receiver_id: str,
    max_pending_observations: int,
) -> None:
    if not queue:
        return

    _persist_and_bound_pending(
        queue=queue,
        jsonl_log=jsonl_log,
        max_pending_observations=max_pending_observations,
    )
    snapshot = queue.upload_snapshot()
    if not snapshot:
        return

    await asyncio.to_thread(uploader.upload, receiver_id, snapshot)
    queue.mark_uploaded(len(snapshot))


def validate_receiver_id(race: RaceConfig, receiver_id: str) -> None:
    checkpoint_for_receiver(race, receiver_id)


async def run_ble_receiver(
    race_path: Path,
    athletes_path: Path,
    receiver_id: str,
    service_url: str,
    jsonl_log: Path,
    batch_size: int = 10,
    flush_interval_sec: float = 2.0,
    max_pending_observations: int = 5000,
) -> None:
    if max_pending_observations < 1:
        raise ValueError("max_pending_observations must be at least 1")

    race = load_race_config(race_path)
    validate_receiver_id(race, receiver_id)
    athletes = load_athletes(athletes_path)
    build_beacon_lookup(athletes)
    uploader = ReceiverUploader(service_url)

    pending = _PendingObservationQueue()
    last_flush = time.monotonic()
    next_upload_attempt = 0.0
    retry_backoff_sec = 1.0
    max_retry_backoff_sec = 30.0

    def detection_callback(_device: object, advertisement_data: object) -> None:
        manufacturer_data = getattr(advertisement_data, "manufacturer_data", {})
        beacon = parse_ibeacon_manufacturer_data(manufacturer_data)
        if beacon is None:
            return

        timestamp_wall = datetime.now(timezone.utc).isoformat()
        timestamp_monotonic = time.monotonic()
        rssi = int(getattr(advertisement_data, "rssi"))
        pending.append(
            upload_detection_from_ibeacon(
                beacon=beacon,
                rssi=rssi,
                timestamp_wall=timestamp_wall,
                timestamp_monotonic=timestamp_monotonic,
            )
        )

    try:
        async with BleakScanner(detection_callback):
            while True:
                await asyncio.sleep(0.25)
                now = time.monotonic()
                if not pending:
                    last_flush = now
                    continue

                limit_exceeded = len(pending) > max_pending_observations
                flush_due = (
                    len(pending) >= batch_size
                    or now - last_flush >= flush_interval_sec
                    or limit_exceeded
                )
                if not flush_due:
                    continue

                if now < next_upload_attempt:
                    _persist_and_bound_pending(
                        queue=pending,
                        jsonl_log=jsonl_log,
                        max_pending_observations=max_pending_observations,
                    )
                    last_flush = now
                    continue

                try:
                    await _flush_and_upload_pending(
                        queue=pending,
                        jsonl_log=jsonl_log,
                        uploader=uploader,
                        receiver_id=receiver_id,
                        max_pending_observations=max_pending_observations,
                    )
                except Exception as error:
                    print(
                        "receiver upload failed; retrying in "
                        f"{retry_backoff_sec:.1f}s: {error}",
                        file=sys.stderr,
                    )
                    next_upload_attempt = now + retry_backoff_sec
                    retry_backoff_sec = min(
                        retry_backoff_sec * 2.0, max_retry_backoff_sec
                    )
                    last_flush = now
                    continue

                next_upload_attempt = 0.0
                retry_backoff_sec = 1.0
                last_flush = now
    finally:
        pending.flush_to_jsonl(jsonl_log)
