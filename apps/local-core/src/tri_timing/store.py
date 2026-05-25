from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Any


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sequence_counter (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO sequence_counter (id, value) VALUES (1, 0);

            CREATE TABLE IF NOT EXISTS raw_detections (
              local_sequence_number INTEGER PRIMARY KEY,
              race_id TEXT NOT NULL,
              receiver_id TEXT NOT NULL,
              checkpoint_id TEXT NOT NULL,
              beacon_uuid TEXT NOT NULL,
              beacon_major INTEGER NOT NULL,
              beacon_minor INTEGER NOT NULL,
              rssi INTEGER NOT NULL,
              timestamp_wall TEXT NOT NULL,
              timestamp_monotonic REAL NOT NULL,
              process_instance_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accepted_route_events (
              local_sequence_number INTEGER PRIMARY KEY,
              race_id TEXT NOT NULL,
              athlete_id TEXT NOT NULL,
              route_event_id TEXT NOT NULL,
              checkpoint_id TEXT NOT NULL,
              pass_candidate_id TEXT,
              event_time_wall TEXT NOT NULL,
              confidence TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_outbox (
              local_sequence_number INTEGER PRIMARY KEY,
              idempotency_key TEXT NOT NULL UNIQUE,
              payload_hash TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT
            );
            """
        )
        self.conn.commit()

    def _next_sequence(self) -> int:
        row = self.conn.execute(
            "UPDATE sequence_counter SET value = value + 1 WHERE id = 1 RETURNING value"
        ).fetchone()
        if row is None:
            raise RuntimeError("sequence counter is not initialized")
        return int(row["value"])

    def append_raw_detection(
        self,
        *,
        race_id: str,
        receiver_id: str,
        checkpoint_id: str,
        beacon_uuid: str,
        beacon_major: int,
        beacon_minor: int,
        rssi: int,
        timestamp_wall: str,
        timestamp_monotonic: float,
        process_instance_id: str,
    ) -> int:
        with self.conn:
            sequence = self._next_sequence()
            self.conn.execute(
                """
                INSERT INTO raw_detections (
                  local_sequence_number, race_id, receiver_id, checkpoint_id,
                  beacon_uuid, beacon_major, beacon_minor, rssi,
                  timestamp_wall, timestamp_monotonic, process_instance_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    race_id,
                    receiver_id,
                    checkpoint_id,
                    beacon_uuid,
                    beacon_major,
                    beacon_minor,
                    rssi,
                    timestamp_wall,
                    timestamp_monotonic,
                    process_instance_id,
                ),
            )
            return sequence

    def append_accepted_route_event(
        self,
        *,
        race_id: str,
        athlete_id: str,
        route_event_id: str,
        checkpoint_id: str,
        pass_candidate_id: str | None,
        event_time_wall: str,
        confidence: str,
    ) -> int:
        with self.conn:
            sequence = self._next_sequence()
            self.conn.execute(
                """
                INSERT INTO accepted_route_events (
                  local_sequence_number, race_id, athlete_id, route_event_id,
                  checkpoint_id, pass_candidate_id, event_time_wall, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    race_id,
                    athlete_id,
                    route_event_id,
                    checkpoint_id,
                    pass_candidate_id,
                    event_time_wall,
                    confidence,
                ),
            )
            payload = {
                "type": "accepted_route_event",
                "local_sequence_number": sequence,
                "race_id": race_id,
                "athlete_id": athlete_id,
                "route_event_id": route_event_id,
                "checkpoint_id": checkpoint_id,
                "event_time_wall": event_time_wall,
                "confidence": confidence,
            }
            payload_json = json.dumps(payload, sort_keys=True)
            self.conn.execute(
                """
                INSERT INTO sync_outbox (
                  local_sequence_number, idempotency_key, payload_hash, payload_json, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    sequence,
                    f"{race_id}:{sequence}",
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                    payload_json,
                ),
            )
            return sequence

    def raw_detections(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM raw_detections ORDER BY local_sequence_number"
        ).fetchall()
        return [dict(row) for row in rows]

    def accepted_route_events(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM accepted_route_events ORDER BY local_sequence_number"
        ).fetchall()
        return [dict(row) for row in rows]

    def sync_outbox(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM sync_outbox ORDER BY local_sequence_number"
        ).fetchall()
        return [dict(row) for row in rows]
