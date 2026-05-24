# BLE Timing Local Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the raceable local Python core: config loading, SQLite append-only store, route compiler, pass detector, race engine, synthetic replay CLI, and a BLE scanner adapter boundary.

**Architecture:** The local Python package is the official timing authority. SQLite is the canonical append-only store; raw detections become pass candidates, and only expected route events advance athlete state. BLE scanner code is isolated behind an adapter so core logic is testable with synthetic detections before hardware arrives.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `pydantic`, `PyYAML`, SQLite via stdlib `sqlite3`, optional `bleak` for hardware scanning.

**Python tooling:** Use `uv` for dependency sync and command execution. Prefer `uv run pytest ...` and `uv run tri-timing ...` over direct `python -m ...` commands.

---

## Scope

This plan intentionally covers only the local core. Later plans should cover:

- React admin UI.
- Cloudflare spectator sync.
- R2 export/backup workflow.
- Polished replay/review UI.

## File Structure

- Create: `pyproject.toml` - Python package metadata and test dependencies.
- Create: `src/tri_timing/__init__.py` - package marker.
- Create: `src/tri_timing/models.py` - shared dataclasses/enums for detections, candidates, route events, decisions.
- Create: `src/tri_timing/config.py` - YAML/CSV config parsing and validation.
- Create: `src/tri_timing/route.py` - compile human route config into ordered route events.
- Create: `src/tri_timing/store.py` - SQLite schema, append-only writes, projection reads.
- Create: `src/tri_timing/detector.py` - RSSI/window pass candidate detector.
- Create: `src/tri_timing/engine.py` - race phase, mass start, route advancement, manual corrections.
- Create: `src/tri_timing/scanner.py` - BLE scanner adapter interface plus synthetic scanner.
- Create: `src/tri_timing/cli.py` - command-line entry points for init, replay, and synthetic race.
- Create: `tests/fixtures/race.yaml` - sample duathlon route config.
- Create: `tests/fixtures/athletes.csv` - sample athletes/beacons.
- Create: `tests/test_config_route.py` - config and route compiler tests.
- Create: `tests/test_store.py` - SQLite append/projection tests.
- Create: `tests/test_detector.py` - pass detector tests.
- Create: `tests/test_engine.py` - route advancement and start suppression tests.
- Create: `tests/test_cli_replay.py` - synthetic replay acceptance test.

---

### Task 1: Python Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/tri_timing/__init__.py`
- Create: `tests/test_import.py`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_import.py`:

```python
def test_package_imports():
    import tri_timing

    assert tri_timing.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_import.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tri_timing'`.

- [ ] **Step 3: Add project metadata**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tri-timing"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pydantic>=2.7",
  "PyYAML>=6.0",
  "bleak>=0.22",
]

[dependency-groups]
dev = [
  "pytest>=8.2",
]

[project.scripts]
tri-timing = "tri_timing.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 4: Add package marker**

Create `src/tri_timing/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_import.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/tri_timing/__init__.py tests/test_import.py
git commit -m "chore: scaffold python timing package"
```

---

### Task 2: Config Models And Route Compiler

**Files:**
- Create: `src/tri_timing/models.py`
- Create: `src/tri_timing/config.py`
- Create: `src/tri_timing/route.py`
- Create: `tests/fixtures/race.yaml`
- Create: `tests/fixtures/athletes.csv`
- Create: `tests/test_config_route.py`

- [ ] **Step 1: Write route compiler tests**

Create `tests/fixtures/race.yaml`:

```yaml
race_id: duathlon-demo
name: Demo Duathlon
start:
  mode: mass_button
  checkpoint_id: gate
  start_grace_sec: 90
checkpoints:
  - id: gate
    name: Shared Gate
receivers:
  - id: laptop-dongle-1
    checkpoint_id: gate
route:
  - id: run1
    sport: run
    checkpoint_id: gate
    laps: 4
    min_lap_elapsed_sec: 360
    detection_policy_id: lap_normal
  - id: t1
    kind: transition
    in_event_id: run1_complete_t1_in
    out_event_id: t1_out_bike_start
    checkpoint_id: gate
    min_transition_sec: 30
    detection_policy_id: transition_strict
  - id: bike
    sport: bike
    checkpoint_id: gate
    laps: 3
    min_lap_elapsed_sec: 600
    detection_policy_id: lap_normal
  - id: t2
    kind: transition
    in_event_id: bike_complete_t2_in
    out_event_id: t2_out_run2_start
    checkpoint_id: gate
    min_transition_sec: 30
    detection_policy_id: transition_strict
  - id: run2
    sport: run
    checkpoint_id: gate
    laps: 4
    min_lap_elapsed_sec: 360
    detection_policy_id: lap_normal
detection_policies:
  lap_normal:
    strong_rssi_threshold: -70
    close_rssi_threshold: -82
    min_packets: 3
    window_sec: 6
    clear_sec: 3
    cooldown_sec: 45
  transition_strict:
    strong_rssi_threshold: -62
    close_rssi_threshold: -78
    min_packets: 3
    window_sec: 4
    clear_sec: 5
    cooldown_sec: 30
```

Create `tests/fixtures/athletes.csv`:

```csv
athlete_id,bib,name,beacon_uuid,beacon_major,beacon_minor
A001,1,Alice,11111111-1111-1111-1111-111111111111,1,1
A002,2,Bob,11111111-1111-1111-1111-111111111111,1,2
```

Create `tests/test_config_route.py`:

```python
from pathlib import Path

from tri_timing.config import load_race_config, load_athletes
from tri_timing.route import compile_route


def test_loads_race_and_athletes():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))

    assert race.race_id == "duathlon-demo"
    assert race.start.start_grace_sec == 90
    assert athletes[0].athlete_id == "A001"
    assert athletes[1].beacon_minor == 2


def test_compile_route_expands_laps_and_transitions():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    events = compile_route(race)

    assert [event.id for event in events] == [
        "run1_lap1_complete",
        "run1_lap2_complete",
        "run1_lap3_complete",
        "run1_complete_t1_in",
        "t1_out_bike_start",
        "bike_lap1_complete",
        "bike_lap2_complete",
        "bike_complete_t2_in",
        "t2_out_run2_start",
        "run2_lap1_complete",
        "run2_lap2_complete",
        "run2_lap3_complete",
        "finish",
    ]
    assert events[3].detection_policy_id == "lap_normal"
    assert events[4].detection_policy_id == "transition_strict"
    assert events[-1].kind == "finish"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_route.py -v`

Expected: FAIL with `ModuleNotFoundError` for `tri_timing.config`.

- [ ] **Step 3: Add shared models**

Create `src/tri_timing/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RacePhase(StrEnum):
    PRE_START = "pre_start"
    ARMED = "armed"
    LIVE = "live"
    CLOSED = "closed"


@dataclass(frozen=True)
class StartConfig:
    mode: str
    checkpoint_id: str
    start_grace_sec: int


@dataclass(frozen=True)
class CheckpointConfig:
    id: str
    name: str


@dataclass(frozen=True)
class ReceiverConfig:
    id: str
    checkpoint_id: str


@dataclass(frozen=True)
class DetectionPolicy:
    id: str
    strong_rssi_threshold: int
    close_rssi_threshold: int
    min_packets: int
    window_sec: int
    clear_sec: int
    cooldown_sec: int


@dataclass(frozen=True)
class RouteSegment:
    id: str
    checkpoint_id: str
    sport: str | None = None
    kind: str | None = None
    laps: int | None = None
    min_lap_elapsed_sec: int | None = None
    min_transition_sec: int | None = None
    detection_policy_id: str = "lap_normal"
    in_event_id: str | None = None
    out_event_id: str | None = None


@dataclass(frozen=True)
class RaceConfig:
    race_id: str
    name: str
    start: StartConfig
    checkpoints: list[CheckpointConfig]
    receivers: list[ReceiverConfig]
    route: list[RouteSegment]
    detection_policies: dict[str, DetectionPolicy]


@dataclass(frozen=True)
class Athlete:
    athlete_id: str
    bib: str
    name: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int


@dataclass(frozen=True)
class RouteEvent:
    index: int
    id: str
    label: str
    checkpoint_id: str
    kind: str
    sport: str | None
    min_elapsed_sec: int
    cooldown_sec: int
    detection_policy_id: str
    manual_allowed: bool = True
```

- [ ] **Step 4: Add config loader**

Create `src/tri_timing/config.py`:

```python
from __future__ import annotations

import csv
from pathlib import Path

import yaml

from tri_timing.models import (
    Athlete,
    CheckpointConfig,
    DetectionPolicy,
    RaceConfig,
    ReceiverConfig,
    RouteSegment,
    StartConfig,
)


def load_race_config(path: Path) -> RaceConfig:
    data = yaml.safe_load(path.read_text())
    policies = {
        policy_id: DetectionPolicy(id=policy_id, **policy)
        for policy_id, policy in data["detection_policies"].items()
    }
    return RaceConfig(
        race_id=data["race_id"],
        name=data["name"],
        start=StartConfig(**data["start"]),
        checkpoints=[CheckpointConfig(**item) for item in data["checkpoints"]],
        receivers=[ReceiverConfig(**item) for item in data["receivers"]],
        route=[RouteSegment(**item) for item in data["route"]],
        detection_policies=policies,
    )


def load_athletes(path: Path) -> list[Athlete]:
    with path.open(newline="") as file:
        rows = csv.DictReader(file)
        return [
            Athlete(
                athlete_id=row["athlete_id"],
                bib=row["bib"],
                name=row["name"],
                beacon_uuid=row["beacon_uuid"],
                beacon_major=int(row["beacon_major"]),
                beacon_minor=int(row["beacon_minor"]),
            )
            for row in rows
        ]
```

- [ ] **Step 5: Add route compiler**

Create `src/tri_timing/route.py`:

```python
from __future__ import annotations

from tri_timing.models import RaceConfig, RouteEvent, RouteSegment


def compile_route(race: RaceConfig) -> list[RouteEvent]:
    events: list[RouteEvent] = []

    for segment_index, segment in enumerate(race.route):
        next_segment = race.route[segment_index + 1] if segment_index + 1 < len(race.route) else None
        if segment.kind == "transition":
            events.append(_transition_out_event(len(events), segment))
            continue
        if segment.laps is None or segment.laps < 1:
            raise ValueError(f"Segment {segment.id} must define laps >= 1")
        for lap_number in range(1, segment.laps + 1):
            is_final_lap = lap_number == segment.laps
            is_final_segment = next_segment is None
            if is_final_lap and is_final_segment:
                event_id = "finish"
                kind = "finish"
                label = "Finish"
            elif is_final_lap and next_segment and next_segment.kind == "transition":
                event_id = next_segment.in_event_id or f"{segment.id}_complete_{next_segment.id}_in"
                kind = "stage_end_transition_in"
                label = f"{segment.id} complete / {next_segment.id} in"
            elif is_final_lap:
                event_id = f"{segment.id}_complete"
                kind = "stage_end"
                label = f"{segment.id} complete"
            else:
                event_id = f"{segment.id}_lap{lap_number}_complete"
                kind = "lap"
                label = f"{segment.id} lap {lap_number} complete"
            policy = race.detection_policies[segment.detection_policy_id]
            events.append(
                RouteEvent(
                    index=len(events),
                    id=event_id,
                    label=label,
                    checkpoint_id=segment.checkpoint_id,
                    kind=kind,
                    sport=segment.sport,
                    min_elapsed_sec=segment.min_lap_elapsed_sec or 0,
                    cooldown_sec=policy.cooldown_sec,
                    detection_policy_id=segment.detection_policy_id,
                )
            )
    return events


def _transition_out_event(index: int, segment: RouteSegment) -> RouteEvent:
    return RouteEvent(
        index=index,
        id=segment.out_event_id or f"{segment.id}_out",
        label=f"{segment.id} out",
        checkpoint_id=segment.checkpoint_id,
        kind="transition_out",
        sport=None,
        min_elapsed_sec=segment.min_transition_sec or 0,
        cooldown_sec=0,
        detection_policy_id=segment.detection_policy_id,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_route.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tri_timing/models.py src/tri_timing/config.py src/tri_timing/route.py tests/fixtures/race.yaml tests/fixtures/athletes.csv tests/test_config_route.py
git commit -m "feat: compile ordered route config"
```

---

### Task 3: SQLite Canonical Store

**Files:**
- Create: `src/tri_timing/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write store tests**

Create `tests/test_store.py`:

```python
from tri_timing.store import EventStore


def test_raw_detection_append_assigns_sequence(tmp_path):
    store = EventStore(tmp_path / "race.db")
    first = store.append_raw_detection(
        race_id="duathlon-demo",
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=2,
        rssi=-61,
        timestamp_wall="2026-05-25T08:00:00+08:00",
        timestamp_monotonic=12.5,
        process_instance_id="proc-1",
    )
    second = store.append_raw_detection(
        race_id="duathlon-demo",
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=2,
        rssi=-60,
        timestamp_wall="2026-05-25T08:00:01+08:00",
        timestamp_monotonic=13.5,
        process_instance_id="proc-1",
    )

    assert first == 1
    assert second == 2
    assert [row["local_sequence_number"] for row in store.raw_detections()] == [1, 2]


def test_append_accepted_event_also_enqueues_sync(tmp_path):
    store = EventStore(tmp_path / "race.db")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-demo",
        athlete_id="A002",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T08:07:00+08:00",
        confidence="high",
    )

    events = store.accepted_route_events()
    outbox = store.sync_outbox()

    assert sequence == 1
    assert events[0]["route_event_id"] == "run1_lap1_complete"
    assert outbox[0]["status"] == "pending"
    assert outbox[0]["idempotency_key"] == "duathlon-demo:1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`

Expected: FAIL with `ModuleNotFoundError` for `tri_timing.store`.

- [ ] **Step 3: Implement SQLite store**

Create `src/tri_timing/store.py`:

```python
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

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
        row = self.conn.execute("SELECT value FROM sequence_counter WHERE id = 1").fetchone()
        next_value = int(row["value"]) + 1
        self.conn.execute("UPDATE sequence_counter SET value = ? WHERE id = 1", (next_value,))
        return next_value

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
        rows = self.conn.execute("SELECT * FROM raw_detections ORDER BY local_sequence_number").fetchall()
        return [dict(row) for row in rows]

    def accepted_route_events(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM accepted_route_events ORDER BY local_sequence_number").fetchall()
        return [dict(row) for row in rows]

    def sync_outbox(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM sync_outbox ORDER BY local_sequence_number").fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tri_timing/store.py tests/test_store.py
git commit -m "feat: add sqlite event store"
```

---

### Task 4: RSSI Pass Detector

**Files:**
- Modify: `src/tri_timing/models.py`
- Create: `src/tri_timing/detector.py`
- Create: `tests/test_detector.py`

- [ ] **Step 1: Write detector tests**

Create `tests/test_detector.py`:

```python
from tri_timing.detector import PassDetector
from tri_timing.models import DetectionPolicy


def policy() -> DetectionPolicy:
    return DetectionPolicy(
        id="transition_strict",
        strong_rssi_threshold=-62,
        close_rssi_threshold=-78,
        min_packets=3,
        window_sec=4,
        clear_sec=3,
        cooldown_sec=30,
    )


def test_detector_uses_peak_time_and_closes_after_clear():
    detector = PassDetector(policy())

    assert detector.observe(timestamp_sec=10, rssi=-75) is None
    assert detector.observe(timestamp_sec=11, rssi=-61) is None
    assert detector.observe(timestamp_sec=12, rssi=-58) is None
    assert detector.observe(timestamp_sec=13, rssi=-60) is None
    assert detector.observe(timestamp_sec=14, rssi=-80) is None
    assert detector.observe(timestamp_sec=17, rssi=-81) is not None

    candidate = detector.last_candidate
    assert candidate is not None
    assert candidate.peak_time_sec == 12
    assert candidate.strongest_rssi == -58
    assert candidate.packet_count == 5


def test_detector_requires_clear_before_new_candidate():
    detector = PassDetector(policy())
    for timestamp, rssi in [(10, -60), (11, -59), (12, -58), (16, -80)]:
        detector.observe(timestamp_sec=timestamp, rssi=rssi)

    assert detector.last_candidate is not None
    assert detector.observe(timestamp_sec=20, rssi=-60) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_detector.py -v`

Expected: FAIL with `ModuleNotFoundError` for `tri_timing.detector`.

- [ ] **Step 3: Add candidate model**

Append to `src/tri_timing/models.py`:

```python

@dataclass(frozen=True)
class PassCandidate:
    candidate_id: str
    opened_at_sec: float
    peak_time_sec: float
    closed_at_sec: float
    strongest_rssi: int
    packet_count: int
    confidence: str
```

- [ ] **Step 4: Implement detector**

Create `src/tri_timing/detector.py`:

```python
from __future__ import annotations

from tri_timing.models import DetectionPolicy, PassCandidate


class PassDetector:
    def __init__(self, policy: DetectionPolicy):
        self.policy = policy
        self._samples: list[tuple[float, int]] = []
        self._candidate_samples: list[tuple[float, int]] = []
        self._candidate_opened_at: float | None = None
        self._last_strong_time: float | None = None
        self._last_closed_at: float | None = None
        self.last_candidate: PassCandidate | None = None

    def observe(self, *, timestamp_sec: float, rssi: int) -> PassCandidate | None:
        self._samples.append((timestamp_sec, rssi))
        self._samples = [
            sample
            for sample in self._samples
            if timestamp_sec - sample[0] <= self.policy.window_sec
        ]

        if self._last_closed_at is not None:
            if timestamp_sec - self._last_closed_at < self.policy.cooldown_sec:
                return None

        if rssi >= self.policy.strong_rssi_threshold and self._candidate_opened_at is None:
            self._candidate_opened_at = timestamp_sec
            self._candidate_samples = []

        if self._candidate_opened_at is not None:
            self._candidate_samples.append((timestamp_sec, rssi))

        if rssi >= self.policy.strong_rssi_threshold:
            self._last_strong_time = timestamp_sec

        if self._candidate_opened_at is None:
            return None

        strong_samples = [
            sample for sample in self._candidate_samples if sample[1] >= self.policy.strong_rssi_threshold
        ]
        if len(strong_samples) < self.policy.min_packets:
            return None

        clear_started = self._last_strong_time is not None and timestamp_sec - self._last_strong_time >= self.policy.clear_sec
        is_below_close = rssi <= self.policy.close_rssi_threshold
        if not clear_started or not is_below_close:
            return None

        peak_time, peak_rssi = max(self._candidate_samples, key=lambda sample: sample[1])
        candidate = PassCandidate(
            candidate_id=f"candidate-{int(self._candidate_opened_at)}-{int(timestamp_sec)}",
            opened_at_sec=self._candidate_opened_at,
            peak_time_sec=peak_time,
            closed_at_sec=timestamp_sec,
            strongest_rssi=peak_rssi,
            packet_count=len(self._candidate_samples),
            confidence="high" if peak_rssi >= self.policy.strong_rssi_threshold else "medium",
        )
        self.last_candidate = candidate
        self._candidate_opened_at = None
        self._candidate_samples = []
        self._samples = []
        self._last_strong_time = None
        self._last_closed_at = timestamp_sec
        return candidate
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_detector.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tri_timing/models.py src/tri_timing/detector.py tests/test_detector.py
git commit -m "feat: detect rssi pass candidates"
```

---

### Task 5: Race Engine

**Files:**
- Modify: `src/tri_timing/models.py`
- Create: `src/tri_timing/engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write engine tests**

Create `tests/test_engine.py`:

```python
from pathlib import Path

from tri_timing.config import load_race_config
from tri_timing.engine import RaceEngine
from tri_timing.models import PassCandidate
from tri_timing.route import compile_route


def candidate(peak_time: float) -> PassCandidate:
    return PassCandidate(
        candidate_id=f"candidate-{peak_time}",
        opened_at_sec=peak_time - 2,
        peak_time_sec=peak_time,
        closed_at_sec=peak_time + 3,
        strongest_rssi=-55,
        packet_count=5,
        confidence="high",
    )


def test_start_grace_blocks_route_advancement():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)

    decision = engine.apply_pass(
        athlete_id="A001",
        checkpoint_id="gate",
        pass_candidate=candidate(150),
    )

    assert decision.status == "suppressed"
    assert decision.reason == "start_grace"
    assert engine.state_for("A001").next_route_event_index == 0


def test_expected_pass_advances_one_route_event():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)

    decision = engine.apply_pass(
        athlete_id="A001",
        checkpoint_id="gate",
        pass_candidate=candidate(500),
    )

    assert decision.status == "accepted"
    assert decision.route_event_id == "run1_lap1_complete"
    assert engine.state_for("A001").next_route_event_index == 1


def test_too_early_lap_is_stored_but_not_advanced():
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    engine = RaceEngine(race_id=race.race_id, route_events=compile_route(race))
    engine.add_athlete("A001")
    engine.start(race_start_sec=100, start_grace_sec=90)
    engine.apply_pass("A001", "gate", candidate(500))

    decision = engine.apply_pass("A001", "gate", candidate(700))

    assert decision.status == "suppressed"
    assert decision.reason == "too_early"
    assert engine.state_for("A001").next_route_event_index == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v`

Expected: FAIL with `ModuleNotFoundError` for `tri_timing.engine`.

- [ ] **Step 3: Add engine models**

Append to `src/tri_timing/models.py`:

```python

@dataclass
class AthleteState:
    athlete_id: str
    next_route_event_index: int = 0
    last_event_time_sec: float | None = None
    status: str = "racing"


@dataclass(frozen=True)
class RouteDecision:
    status: str
    reason: str | None
    route_event_id: str | None
    event_time_sec: float | None
```

- [ ] **Step 4: Implement race engine**

Create `src/tri_timing/engine.py`:

```python
from __future__ import annotations

from tri_timing.models import AthleteState, PassCandidate, RacePhase, RouteDecision, RouteEvent


class RaceEngine:
    def __init__(self, *, race_id: str, route_events: list[RouteEvent]):
        self.race_id = race_id
        self.route_events = route_events
        self.phase = RacePhase.PRE_START
        self.race_start_sec: float | None = None
        self.start_grace_until_sec: float | None = None
        self._states: dict[str, AthleteState] = {}

    def add_athlete(self, athlete_id: str) -> None:
        self._states[athlete_id] = AthleteState(athlete_id=athlete_id)

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

        if self.start_grace_until_sec is not None and pass_candidate.peak_time_sec < self.start_grace_until_sec:
            return RouteDecision("suppressed", "start_grace", None, None)

        state = self._states[athlete_id]
        if state.next_route_event_index >= len(self.route_events):
            return RouteDecision("suppressed", "already_finished", None, None)

        expected = self.route_events[state.next_route_event_index]
        if expected.checkpoint_id != checkpoint_id:
            return RouteDecision("suppressed", "wrong_checkpoint", None, None)

        baseline = state.last_event_time_sec if state.last_event_time_sec is not None else self.race_start_sec
        if baseline is not None and pass_candidate.peak_time_sec - baseline < expected.min_elapsed_sec:
            return RouteDecision("suppressed", "too_early", expected.id, pass_candidate.peak_time_sec)

        state.next_route_event_index += 1
        state.last_event_time_sec = pass_candidate.peak_time_sec
        if expected.kind == "finish":
            state.status = "finished"

        return RouteDecision("accepted", None, expected.id, pass_candidate.peak_time_sec)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tri_timing/models.py src/tri_timing/engine.py tests/test_engine.py
git commit -m "feat: advance expected route events"
```

---

### Task 6: Scanner Adapter And Synthetic Replay CLI

**Files:**
- Create: `src/tri_timing/scanner.py`
- Create: `src/tri_timing/cli.py`
- Create: `tests/test_cli_replay.py`

- [ ] **Step 1: Write CLI replay test**

Create `tests/test_cli_replay.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_synthetic_replay_exports_accepted_events(tmp_path):
    output_path = tmp_path / "result.json"
    command = [
        sys.executable,
        "-m",
        "tri_timing.cli",
        "synthetic-replay",
        "--race",
        "tests/fixtures/race.yaml",
        "--athletes",
        "tests/fixtures/athletes.csv",
        "--output",
        str(output_path),
    ]

    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(output_path.read_text())

    assert "accepted 1 route event" in result.stdout
    assert data["accepted_events"][0]["athlete_id"] == "A001"
    assert data["accepted_events"][0]["route_event_id"] == "run1_lap1_complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_replay.py -v`

Expected: FAIL because `tri_timing.cli` does not exist.

- [ ] **Step 3: Add scanner adapter boundary**

Create `src/tri_timing/scanner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class BeaconObservation:
    timestamp_sec: float
    timestamp_wall: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    receiver_id: str
    checkpoint_id: str


class Scanner(Protocol):
    def observations(self) -> Iterable[BeaconObservation]:
        raise NotImplementedError


class SyntheticScanner:
    def __init__(self, observations: list[BeaconObservation]):
        self._observations = observations

    def observations(self) -> Iterable[BeaconObservation]:
        return list(self._observations)
```

- [ ] **Step 4: Add replay CLI**

Create `src/tri_timing/cli.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tri_timing.config import load_athletes, load_race_config
from tri_timing.detector import PassDetector
from tri_timing.engine import RaceEngine
from tri_timing.route import compile_route
from tri_timing.scanner import BeaconObservation, SyntheticScanner


def main() -> None:
    parser = argparse.ArgumentParser(prog="tri-timing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    replay = subparsers.add_parser("synthetic-replay")
    replay.add_argument("--race", required=True)
    replay.add_argument("--athletes", required=True)
    replay.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.command == "synthetic-replay":
        synthetic_replay(Path(args.race), Path(args.athletes), Path(args.output))


def synthetic_replay(race_path: Path, athletes_path: Path, output_path: Path) -> None:
    race = load_race_config(race_path)
    athletes = load_athletes(athletes_path)
    route_events = compile_route(race)
    engine = RaceEngine(race_id=race.race_id, route_events=route_events)
    for athlete in athletes:
        engine.add_athlete(athlete.athlete_id)
    engine.start(race_start_sec=100, start_grace_sec=race.start.start_grace_sec)

    athlete = athletes[0]
    observations = [
        BeaconObservation(500, "2026-05-25T08:07:00+08:00", athlete.beacon_uuid, athlete.beacon_major, athlete.beacon_minor, -61, "laptop-dongle-1", "gate"),
        BeaconObservation(501, "2026-05-25T08:07:01+08:00", athlete.beacon_uuid, athlete.beacon_major, athlete.beacon_minor, -56, "laptop-dongle-1", "gate"),
        BeaconObservation(502, "2026-05-25T08:07:02+08:00", athlete.beacon_uuid, athlete.beacon_major, athlete.beacon_minor, -59, "laptop-dongle-1", "gate"),
        BeaconObservation(506, "2026-05-25T08:07:06+08:00", athlete.beacon_uuid, athlete.beacon_major, athlete.beacon_minor, -82, "laptop-dongle-1", "gate"),
    ]
    scanner = SyntheticScanner(observations)
    policy = race.detection_policies["lap_normal"]
    detector = PassDetector(policy)
    accepted_events: list[dict[str, object]] = []

    for observation in scanner.observations():
        candidate = detector.observe(timestamp_sec=observation.timestamp_sec, rssi=observation.rssi)
        if candidate is None:
            continue
        decision = engine.apply_pass(athlete.athlete_id, observation.checkpoint_id, candidate)
        if decision.status == "accepted":
            accepted_events.append(
                {
                    "athlete_id": athlete.athlete_id,
                    "route_event_id": decision.route_event_id,
                    "event_time_sec": decision.event_time_sec,
                }
            )

    output_path.write_text(json.dumps({"accepted_events": accepted_events}, indent=2))
    print(f"accepted {len(accepted_events)} route event")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_replay.py -v`

Expected: PASS.

- [ ] **Step 6: Run full local-core tests**

Run: `uv run pytest -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tri_timing/scanner.py src/tri_timing/cli.py tests/test_cli_replay.py
git commit -m "feat: add synthetic replay cli"
```

---

### Task 7: Local Core Acceptance Check

**Files:**
- Modify: `docs/superpowers/specs/2026-05-25-ble-triathlon-timing-mvp-design.md`
- Create: `docs/local-core-acceptance.md`

- [ ] **Step 1: Create acceptance checklist**

Create `docs/local-core-acceptance.md`:

```markdown
# Local Core Acceptance Checklist

This checklist proves the local Python timing core is ready for admin UI planning.

## Required Commands

```bash
uv run pytest -v
uv run tri-timing synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
cat /tmp/tri-timing-result.json
```

## Expected Result

- Test suite passes.
- Synthetic replay prints `accepted 1 route event`.
- Output JSON contains `run1_lap1_complete` for `A001`.

## Scope Confirmed

- Config loading works.
- Route compiler expands laps and transitions.
- SQLite canonical store assigns durable local sequence numbers.
- Pass detector uses RSSI hysteresis and peak time.
- Race engine blocks start-grace detections.
- Race engine advances only expected route events.
- CLI can run a synthetic replay.
```

- [ ] **Step 2: Run acceptance commands**

Run:

```bash
uv run pytest -v
uv run tri-timing synthetic-replay --race tests/fixtures/race.yaml --athletes tests/fixtures/athletes.csv --output /tmp/tri-timing-result.json
cat /tmp/tri-timing-result.json
```

Expected:

```text
accepted 1 route event
```

and JSON includes:

```json
{
  "athlete_id": "A001",
  "route_event_id": "run1_lap1_complete"
}
```

- [ ] **Step 3: Commit**

```bash
git add docs/local-core-acceptance.md
git commit -m "docs: add local core acceptance checklist"
```

---

## Self-Review Notes

Spec coverage:

- Local authority: covered by `RaceEngine`, `EventStore`, and synthetic replay.
- Ordered route with laps: covered by route compiler tests.
- State-specific detection policies: represented in fixture config and route events.
- SQLite canonical sequence: covered by store tests.
- Pass detector hysteresis and peak timestamp: covered by detector tests.
- Start grace: covered by engine tests.
- Cloud sync: only outbox stub in this plan; full Cloudflare sync gets its own plan.
- React admin: out of scope for this plan; gets its own plan.
- R2 backup: out of scope for this plan; gets its own plan.

Deferred subsystems are named as later plans, not vague implementation gaps.
