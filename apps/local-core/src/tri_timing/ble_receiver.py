from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakScanner

from tri_timing.config import load_athletes, load_race_config
from tri_timing.ibeacon import parse_ibeacon_manufacturer_data
from tri_timing.receiver import (
    ReceiverObservation,
    ReceiverUploader,
    build_beacon_lookup,
    observation_from_ibeacon,
    write_observations_jsonl,
)


async def run_ble_receiver(
    race_path: Path,
    athletes_path: Path,
    receiver_id: str,
    service_url: str,
    jsonl_log: Path,
    batch_size: int = 10,
    flush_interval_sec: float = 2.0,
) -> None:
    race = load_race_config(race_path)
    athletes = load_athletes(athletes_path)
    beacon_lookup = build_beacon_lookup(athletes)
    uploader = ReceiverUploader(service_url)

    pending: list[ReceiverObservation] = []
    persisted_count = 0
    last_flush = time.monotonic()

    def detection_callback(_device: object, advertisement_data: object) -> None:
        manufacturer_data = getattr(advertisement_data, "manufacturer_data", {})
        beacon = parse_ibeacon_manufacturer_data(manufacturer_data)
        if beacon is None:
            return

        observation = observation_from_ibeacon(
            beacon=beacon,
            rssi=int(getattr(advertisement_data, "rssi")),
            timestamp_wall=datetime.now(timezone.utc).isoformat(),
            timestamp_monotonic=time.monotonic(),
            receiver_id=receiver_id,
            race=race,
            beacon_lookup=beacon_lookup,
        )
        if observation is not None:
            pending.append(observation)

    async with BleakScanner(detection_callback):
        while True:
            await asyncio.sleep(0.25)
            now = time.monotonic()
            if not pending:
                last_flush = now
                continue
            if len(pending) < batch_size and now - last_flush < flush_interval_sec:
                continue

            if persisted_count < len(pending):
                write_observations_jsonl(jsonl_log, pending[persisted_count:])
                persisted_count = len(pending)

            try:
                uploader.upload(receiver_id, pending)
            except Exception as error:
                print(f"receiver upload failed: {error}", file=sys.stderr)
                last_flush = now
                continue

            pending.clear()
            persisted_count = 0
            last_flush = now
