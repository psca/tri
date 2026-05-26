# Real BLE Receiver And Detection Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end path from real BLE iBeacon advertisements to local race detections, accepted route events, and admin receiver health.

**Architecture:** The receiver process is a dumb collector: scan, parse, filter, JSONL-log, and POST detections. The FastAPI local service is the timing authority: validate receiver/beacon identity, store raw detections, feed persistent pass detectors, advance route state, and expose receiver health. The admin UI displays receiver health without making timing decisions.

**Tech Stack:** Python 3.11+, `uv`, `bleak`, FastAPI, SQLite, pytest, React, TypeScript, Vite, Vitest.

---

## File Structure

```text
apps/local-core/
  src/tri_timing/ibeacon.py              iBeacon manufacturer data parser
  src/tri_timing/receiver.py             receiver filtering, JSONL log, upload client
  src/tri_timing/ble_receiver.py         bleak scanner adapter
  src/tri_timing/cli.py                  receiver-run command
  src/tri_timing_service/models.py       detection ingest and receiver health API models
  src/tri_timing_service/runtime.py      detection ingest, persistent detectors, health state
  src/tri_timing_service/app.py          /api/detections and /api/receivers/health routes
  tests/test_ibeacon.py
  tests/test_receiver.py
  tests/test_service_api.py

apps/admin/
  src/types.ts                           receiver health types
  src/api.ts                             getReceiverHealth client
  src/App.tsx                            receiver health panel
  src/App.test.tsx                       receiver health UI tests

docs/acceptance/real-ble-receiver.md     hardware validation checklist
README.md                                document receiver command
```

## Task 1: Add iBeacon Parser

**Files:**
- Create: `apps/local-core/src/tri_timing/ibeacon.py`
- Create: `apps/local-core/tests/test_ibeacon.py`

- [ ] **Step 1: Write parser tests**

Create `apps/local-core/tests/test_ibeacon.py`:

```python
from tri_timing.ibeacon import parse_ibeacon_manufacturer_data


def test_parse_ibeacon_manufacturer_data_decodes_uuid_major_minor_power() -> None:
    payload = bytes.fromhex(
        "0215"
        "11111111111111111111111111111111"
        "0001"
        "0002"
        "c5"
    )

    result = parse_ibeacon_manufacturer_data({0x004C: payload})

    assert result is not None
    assert result.uuid == "11111111-1111-1111-1111-111111111111"
    assert result.major == 1
    assert result.minor == 2
    assert result.measured_power == -59


def test_parse_ibeacon_manufacturer_data_ignores_non_ibeacon_payload() -> None:
    assert parse_ibeacon_manufacturer_data({0x004C: b"\x01\x02short"}) is None
    assert parse_ibeacon_manufacturer_data({0x1234: b"\x02\x15" + bytes(21)}) is None
```

- [ ] **Step 2: Run failing parser tests**

```bash
cd apps/local-core
uv run pytest tests/test_ibeacon.py -v
```

Expected: fail because `tri_timing.ibeacon` does not exist.

- [ ] **Step 3: Implement parser**

Create `apps/local-core/src/tri_timing/ibeacon.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


APPLE_COMPANY_ID = 0x004C
IBEACON_PREFIX = b"\x02\x15"
IBEACON_PAYLOAD_LENGTH = 23


@dataclass(frozen=True)
class IBeaconAdvertisement:
    uuid: str
    major: int
    minor: int
    measured_power: int


def parse_ibeacon_manufacturer_data(
    manufacturer_data: dict[int, bytes],
) -> IBeaconAdvertisement | None:
    payload = manufacturer_data.get(APPLE_COMPANY_ID)
    if payload is None:
        return None
    if len(payload) != IBEACON_PAYLOAD_LENGTH:
        return None
    if not payload.startswith(IBEACON_PREFIX):
        return None

    return IBeaconAdvertisement(
        uuid=str(UUID(bytes=payload[2:18])),
        major=int.from_bytes(payload[18:20], byteorder="big"),
        minor=int.from_bytes(payload[20:22], byteorder="big"),
        measured_power=int.from_bytes(payload[22:23], byteorder="big", signed=True),
    )
```

- [ ] **Step 4: Verify parser tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_ibeacon.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing/ibeacon.py apps/local-core/tests/test_ibeacon.py
git commit -m "feat: parse ibeacon advertisements"
```

## Task 2: Add Receiver Filtering, JSONL Logging, And Upload Client

**Files:**
- Create: `apps/local-core/src/tri_timing/receiver.py`
- Create: `apps/local-core/tests/test_receiver.py`

- [ ] **Step 1: Write receiver tests**

Create `apps/local-core/tests/test_receiver.py`:

```python
from pathlib import Path
import json

import httpx
import pytest

from tri_timing.config import load_athletes, load_race_config
from tri_timing.ibeacon import IBeaconAdvertisement
from tri_timing.receiver import (
    ReceiverObservation,
    ReceiverUploader,
    build_beacon_lookup,
    observation_from_ibeacon,
    write_observations_jsonl,
)


def test_build_beacon_lookup_maps_configured_athletes() -> None:
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))

    lookup = build_beacon_lookup(athletes)

    assert lookup[("11111111-1111-1111-1111-111111111111", 1, 1)].athlete_id == "A001"
    assert lookup[("11111111-1111-1111-1111-111111111111", 1, 2)].athlete_id == "A002"


def test_observation_from_ibeacon_filters_unknown_beacons() -> None:
    race = load_race_config(Path("tests/fixtures/race.yaml"))
    athletes = load_athletes(Path("tests/fixtures/athletes.csv"))
    lookup = build_beacon_lookup(athletes)

    known = observation_from_ibeacon(
        beacon=IBeaconAdvertisement(
            uuid="11111111-1111-1111-1111-111111111111",
            major=1,
            minor=1,
            measured_power=-59,
        ),
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
        receiver_id="laptop-dongle-1",
        race=race,
        beacon_lookup=lookup,
    )
    unknown = observation_from_ibeacon(
        beacon=IBeaconAdvertisement(
            uuid="22222222-2222-2222-2222-222222222222",
            major=1,
            minor=1,
            measured_power=-59,
        ),
        rssi=-70,
        timestamp_wall="2026-05-26T09:00:01+08:00",
        timestamp_monotonic=101.5,
        receiver_id="laptop-dongle-1",
        race=race,
        beacon_lookup=lookup,
    )

    assert known is not None
    assert known.athlete_id == "A001"
    assert known.checkpoint_id == "gate"
    assert unknown is None


def test_write_observations_jsonl_appends_one_json_object_per_line(tmp_path) -> None:
    path = tmp_path / "receiver.jsonl"
    observation = ReceiverObservation(
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        athlete_id="A001",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=1,
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
    )

    write_observations_jsonl(path, [observation])

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [observation.to_payload()]


@pytest.mark.parametrize("status_code,should_raise", [(200, False), (500, True)])
def test_receiver_uploader_posts_detection_batches(status_code, should_raise) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(status_code, json={"stored": 1, "ignored_unknown": 0, "accepted_events": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    uploader = ReceiverUploader("http://local.test", client=client)
    observation = ReceiverObservation(
        receiver_id="laptop-dongle-1",
        checkpoint_id="gate",
        athlete_id="A001",
        beacon_uuid="11111111-1111-1111-1111-111111111111",
        beacon_major=1,
        beacon_minor=1,
        rssi=-61,
        timestamp_wall="2026-05-26T09:00:00+08:00",
        timestamp_monotonic=100.5,
    )

    if should_raise:
        with pytest.raises(httpx.HTTPStatusError):
            uploader.upload("laptop-dongle-1", [observation])
    else:
        uploader.upload("laptop-dongle-1", [observation])
        assert requests[0]["receiver_id"] == "laptop-dongle-1"
        assert requests[0]["detections"][0]["beacon_minor"] == 1
```

- [ ] **Step 2: Run failing receiver tests**

```bash
cd apps/local-core
uv run pytest tests/test_receiver.py -v
```

Expected: fail because `tri_timing.receiver` does not exist.

- [ ] **Step 3: Implement receiver helpers**

Create `apps/local-core/src/tri_timing/receiver.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import httpx

from tri_timing.ibeacon import IBeaconAdvertisement
from tri_timing.models import AthleteConfig, RaceConfig


BeaconKey = tuple[str, int, int]


@dataclass(frozen=True)
class ReceiverObservation:
    receiver_id: str
    checkpoint_id: str
    athlete_id: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    timestamp_wall: str
    timestamp_monotonic: float

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


def build_beacon_lookup(athletes: list[AthleteConfig]) -> dict[BeaconKey, AthleteConfig]:
    return {
        (athlete.beacon_uuid.lower(), athlete.beacon_major, athlete.beacon_minor): athlete
        for athlete in athletes
    }


def checkpoint_for_receiver(race: RaceConfig, receiver_id: str) -> str:
    for receiver in race.receivers:
        if receiver.id == receiver_id:
            return receiver.checkpoint_id
    raise ValueError(f"unknown receiver: {receiver_id}")


def observation_from_ibeacon(
    *,
    beacon: IBeaconAdvertisement,
    rssi: int,
    timestamp_wall: str,
    timestamp_monotonic: float,
    receiver_id: str,
    race: RaceConfig,
    beacon_lookup: dict[BeaconKey, AthleteConfig],
) -> ReceiverObservation | None:
    athlete = beacon_lookup.get((beacon.uuid.lower(), beacon.major, beacon.minor))
    if athlete is None:
        return None
    return ReceiverObservation(
        receiver_id=receiver_id,
        checkpoint_id=checkpoint_for_receiver(race, receiver_id),
        athlete_id=athlete.athlete_id,
        beacon_uuid=beacon.uuid,
        beacon_major=beacon.major,
        beacon_minor=beacon.minor,
        rssi=rssi,
        timestamp_wall=timestamp_wall,
        timestamp_monotonic=timestamp_monotonic,
    )


def write_observations_jsonl(path: Path, observations: list[ReceiverObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for observation in observations:
            handle.write(json.dumps(observation.to_payload(), sort_keys=True) + "\n")


class ReceiverUploader:
    def __init__(self, service_url: str, *, client: httpx.Client | None = None):
        self.service_url = service_url.rstrip("/")
        self._client = client or httpx.Client(timeout=5)

    def upload(self, receiver_id: str, observations: list[ReceiverObservation]) -> dict:
        response = self._client.post(
            f"{self.service_url}/api/detections",
            json={
                "receiver_id": receiver_id,
                "detections": [observation.to_payload() for observation in observations],
            },
        )
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 4: Verify receiver tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_receiver.py -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing/receiver.py apps/local-core/tests/test_receiver.py
git commit -m "feat: add receiver filtering and upload helpers"
```

## Task 3: Add Detection Ingest API And Receiver Health

**Files:**
- Modify: `apps/local-core/src/tri_timing_service/models.py`
- Modify: `apps/local-core/src/tri_timing_service/runtime.py`
- Modify: `apps/local-core/src/tri_timing_service/app.py`
- Modify: `apps/local-core/tests/test_service_api.py`

- [ ] **Step 1: Add service API tests**

Append tests to `apps/local-core/tests/test_service_api.py`:

```python
def _detection_payload(*, minor: int = 1, rssi: int = -55, timestamp_sec: float = 500):
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
    assert response.json()["accepted_events"][0]["route_event_id"] == "run1_lap1_complete"
    assert state["athletes"][0]["next_event_id"] == "run1_lap2_complete"


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
```

- [ ] **Step 2: Run failing service API tests**

```bash
cd apps/local-core
uv run pytest tests/test_service_api.py -k 'detection_ingest or receiver_health' -v
```

Expected: fail because endpoints and models do not exist.

- [ ] **Step 3: Add service models**

Modify `apps/local-core/src/tri_timing_service/models.py`:

```python
class DetectionIngestItem(BaseModel):
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    timestamp_wall: str
    timestamp_monotonic: float


class DetectionIngestRequest(BaseModel):
    receiver_id: str
    detections: list[DetectionIngestItem]


class DetectionAcceptedEventView(BaseModel):
    athlete_id: str
    route_event_id: str


class DetectionIngestResponse(BaseModel):
    stored: int
    ignored_unknown: int
    accepted_events: list[DetectionAcceptedEventView]


class ReceiverBeaconHealthView(BaseModel):
    athlete_id: str
    beacon_uuid: str
    beacon_major: int
    beacon_minor: int
    rssi: int
    timestamp_wall: str


class ReceiverHealthView(BaseModel):
    receiver_id: str
    checkpoint_id: str
    status: str
    last_packet_wall: str | None
    known_packets: int
    unknown_packets: int
    latest_known_beacons: list[ReceiverBeaconHealthView]


class ReceiverHealthResponse(BaseModel):
    receivers: list[ReceiverHealthView]
```

Also import these models in `app.py` and `runtime.py`.

- [ ] **Step 4: Implement runtime ingest and health**

Modify `RaceRuntime.__init__` in `apps/local-core/src/tri_timing_service/runtime.py`:

```python
self._athletes_by_beacon = {
    (athlete.beacon_uuid.lower(), athlete.beacon_major, athlete.beacon_minor): athlete
    for athlete in self._athletes
}
self._checkpoint_by_receiver = {
    receiver.id: receiver.checkpoint_id for receiver in self._race_config.receivers
}
self._live_detectors: dict[tuple[str, str], PassDetector] = {}
self._receiver_health: dict[str, dict] = {
    receiver.id: {
        "receiver_id": receiver.id,
        "checkpoint_id": receiver.checkpoint_id,
        "last_packet_wall": None,
        "last_packet_monotonic": None,
        "known_packets": 0,
        "unknown_packets": 0,
        "latest_known_beacons": {},
    }
    for receiver in self._race_config.receivers
}
```

Add methods:

```python
def ingest_detections(
    self, request: DetectionIngestRequest
) -> DetectionIngestResponse:
    checkpoint_id = self._checkpoint_by_receiver.get(request.receiver_id)
    if checkpoint_id is None:
        raise ValueError(f"unknown receiver: {request.receiver_id}")

    stored = 0
    ignored_unknown = 0
    accepted_events: list[DetectionAcceptedEventView] = []

    for detection in request.detections:
        health = self._receiver_health[request.receiver_id]
        health["last_packet_wall"] = detection.timestamp_wall
        health["last_packet_monotonic"] = detection.timestamp_monotonic

        athlete = self._athletes_by_beacon.get(
            (
                detection.beacon_uuid.lower(),
                detection.beacon_major,
                detection.beacon_minor,
            )
        )
        if athlete is None:
            ignored_unknown += 1
            health["unknown_packets"] += 1
            continue

        health["known_packets"] += 1
        health["latest_known_beacons"][athlete.athlete_id] = {
            "athlete_id": athlete.athlete_id,
            "beacon_uuid": detection.beacon_uuid,
            "beacon_major": detection.beacon_major,
            "beacon_minor": detection.beacon_minor,
            "rssi": detection.rssi,
            "timestamp_wall": detection.timestamp_wall,
        }

        self._store.append_raw_detection(
            race_id=self._race_config.race_id,
            receiver_id=request.receiver_id,
            checkpoint_id=checkpoint_id,
            beacon_uuid=detection.beacon_uuid,
            beacon_major=detection.beacon_major,
            beacon_minor=detection.beacon_minor,
            rssi=detection.rssi,
            timestamp_wall=detection.timestamp_wall,
            timestamp_monotonic=detection.timestamp_monotonic,
            process_instance_id="receiver",
        )
        stored += 1

        accepted = self._maybe_accept_detection(
            athlete_id=athlete.athlete_id,
            checkpoint_id=checkpoint_id,
            rssi=detection.rssi,
            timestamp_wall=detection.timestamp_wall,
            timestamp_monotonic=detection.timestamp_monotonic,
        )
        if accepted is not None:
            accepted_events.append(accepted)

    return DetectionIngestResponse(
        stored=stored,
        ignored_unknown=ignored_unknown,
        accepted_events=accepted_events,
    )


def _maybe_accept_detection(
    self,
    *,
    athlete_id: str,
    checkpoint_id: str,
    rssi: int,
    timestamp_wall: str,
    timestamp_monotonic: float,
) -> DetectionAcceptedEventView | None:
    if self._phase != "live":
        return None

    engine_state = self._engine.state_for(athlete_id)
    if engine_state.next_route_event_index >= len(self._route):
        return None

    expected_event = self._route[engine_state.next_route_event_index]
    if expected_event.checkpoint_id != checkpoint_id:
        return None

    detector_key = (athlete_id, expected_event.id)
    detector = self._live_detectors.get(detector_key)
    if detector is None:
        detector = PassDetector(
            self._race_config.detection_policies[expected_event.detection_policy_id]
        )
        self._live_detectors[detector_key] = detector

    candidate = detector.observe(timestamp_sec=timestamp_monotonic, rssi=rssi)
    if candidate is None:
        return None

    decision = self._engine.apply_pass(athlete_id, checkpoint_id, candidate)
    if decision.status != "accepted" or decision.route_event_id is None:
        return None

    self._store.append_accepted_route_event(
        race_id=self._race_config.race_id,
        athlete_id=athlete_id,
        route_event_id=decision.route_event_id,
        checkpoint_id=checkpoint_id,
        pass_candidate_id=candidate.candidate_id,
        event_time_wall=timestamp_wall,
        confidence=candidate.confidence,
    )
    return DetectionAcceptedEventView(
        athlete_id=athlete_id,
        route_event_id=decision.route_event_id,
    )


def receiver_health(self) -> ReceiverHealthResponse:
    receivers = []
    for row in self._receiver_health.values():
        status = "silent"
        if row["last_packet_monotonic"] is not None:
            status = "online"
        receivers.append(
            ReceiverHealthView(
                receiver_id=row["receiver_id"],
                checkpoint_id=row["checkpoint_id"],
                status=status,
                last_packet_wall=row["last_packet_wall"],
                known_packets=row["known_packets"],
                unknown_packets=row["unknown_packets"],
                latest_known_beacons=list(row["latest_known_beacons"].values()),
            )
        )
    return ReceiverHealthResponse(receivers=receivers)
```

Use imported model names from `tri_timing_service.models`. If strict stale/online timing is implemented, keep tests deterministic by allowing `online` after any packet in unit tests.

- [ ] **Step 5: Add FastAPI routes and broadcasting**

Modify `apps/local-core/src/tri_timing_service/app.py`:

```python
from tri_timing_service.models import DetectionIngestRequest
```

Add routes:

```python
@app.post("/api/detections")
async def ingest_detections(request: DetectionIngestRequest):
    try:
        result = get_runtime().ingest_detections(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    broadcaster.publish_state(get_runtime().state())
    return result


@app.get("/api/receivers/health")
async def receiver_health():
    return get_runtime().receiver_health()
```

- [ ] **Step 6: Verify service API tests pass**

```bash
cd apps/local-core
uv run pytest tests/test_service_api.py -k 'detection_ingest or receiver_health' -v
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/local-core/src/tri_timing_service/models.py apps/local-core/src/tri_timing_service/runtime.py apps/local-core/src/tri_timing_service/app.py apps/local-core/tests/test_service_api.py
git commit -m "feat: ingest receiver detections"
```

## Task 4: Add Bleak Receiver CLI

**Files:**
- Create: `apps/local-core/src/tri_timing/ble_receiver.py`
- Modify: `apps/local-core/src/tri_timing/cli.py`
- Modify: `apps/local-core/tests/test_receiver.py`

- [ ] **Step 1: Add CLI argument test**

Append to `apps/local-core/tests/test_receiver.py`:

```python
def test_receiver_command_is_registered() -> None:
    import subprocess

    result = subprocess.run(
        ["uv", "run", "tri-timing", "receiver-run", "--help"],
        cwd=Path(__file__).parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--receiver-id" in result.stdout
    assert "--service-url" in result.stdout
    assert "--jsonl-log" in result.stdout
```

- [ ] **Step 2: Run failing CLI test**

```bash
cd apps/local-core
uv run pytest tests/test_receiver.py::test_receiver_command_is_registered -v
```

Expected: fail because `receiver-run` is not registered.

- [ ] **Step 3: Implement Bleak scanner adapter**

Create `apps/local-core/src/tri_timing/ble_receiver.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import time

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
    *,
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
    last_flush = time.monotonic()

    async def flush_if_needed(force: bool = False) -> None:
        nonlocal pending, last_flush
        if not pending:
            return
        if not force and len(pending) < batch_size and time.monotonic() - last_flush < flush_interval_sec:
            return
        batch = pending
        pending = []
        write_observations_jsonl(jsonl_log, batch)
        try:
            uploader.upload(receiver_id, batch)
        except Exception as error:
            pending = batch + pending
            print(f"receiver upload failed: {error}")
        last_flush = time.monotonic()

    def detection_callback(device, advertisement_data) -> None:
        beacon = parse_ibeacon_manufacturer_data(advertisement_data.manufacturer_data)
        if beacon is None:
            return
        observation = observation_from_ibeacon(
            beacon=beacon,
            rssi=advertisement_data.rssi,
            timestamp_wall=datetime.now(tz=UTC).isoformat(),
            timestamp_monotonic=time.monotonic(),
            receiver_id=receiver_id,
            race=race,
            beacon_lookup=beacon_lookup,
        )
        if observation is not None:
            pending.append(observation)

    scanner = BleakScanner(detection_callback)
    async with scanner:
        print(f"receiver {receiver_id} scanning; log={jsonl_log}")
        while True:
            await asyncio.sleep(0.25)
            await flush_if_needed()
```

This loop intentionally writes known observations to JSONL as part of flush. If upload fails, the batch remains pending and will be retried; already-written JSONL may contain duplicate lines after repeated retries only if implementation writes on each retry. Avoid duplicates by writing before first upload attempt only if the worker can do so cleanly.

- [ ] **Step 4: Register CLI command**

Modify `apps/local-core/src/tri_timing/cli.py`:

```python
import asyncio
from tri_timing.ble_receiver import run_ble_receiver
```

Register parser:

```python
receiver = subparsers.add_parser("receiver-run")
receiver.add_argument("--race", required=True)
receiver.add_argument("--athletes", required=True)
receiver.add_argument("--receiver-id", required=True)
receiver.add_argument("--service-url", default="http://127.0.0.1:8000")
receiver.add_argument("--jsonl-log", required=True)
receiver.add_argument("--batch-size", type=int, default=10)
receiver.add_argument("--flush-interval-sec", type=float, default=2.0)
```

Dispatch:

```python
elif args.command == "receiver-run":
    asyncio.run(
        run_ble_receiver(
            race_path=Path(args.race),
            athletes_path=Path(args.athletes),
            receiver_id=args.receiver_id,
            service_url=args.service_url,
            jsonl_log=Path(args.jsonl_log),
            batch_size=args.batch_size,
            flush_interval_sec=args.flush_interval_sec,
        )
    )
```

- [ ] **Step 5: Verify CLI test passes**

```bash
cd apps/local-core
uv run pytest tests/test_receiver.py::test_receiver_command_is_registered -v
```

Expected: test passes.

- [ ] **Step 6: Commit**

```bash
git add apps/local-core/src/tri_timing/ble_receiver.py apps/local-core/src/tri_timing/cli.py apps/local-core/tests/test_receiver.py
git commit -m "feat: add bleak receiver command"
```

## Task 5: Add Admin Receiver Health Panel

**Files:**
- Modify: `apps/admin/src/types.ts`
- Modify: `apps/admin/src/api.ts`
- Modify: `apps/admin/src/App.tsx`
- Modify: `apps/admin/src/App.test.tsx`
- Modify: `apps/admin/src/styles.css`

- [ ] **Step 1: Add admin tests**

Append to `apps/admin/src/App.test.tsx`:

```tsx
test("renders receiver health panel", async () => {
  vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/receivers/health")) {
      return new Response(
        JSON.stringify({
          receivers: [
            {
              receiver_id: "laptop-dongle-1",
              checkpoint_id: "gate",
              status: "online",
              last_packet_wall: "2026-05-26T09:00:00+08:00",
              known_packets: 3,
              unknown_packets: 1,
              latest_known_beacons: [
                {
                  athlete_id: "A001",
                  beacon_uuid: "11111111-1111-1111-1111-111111111111",
                  beacon_major: 1,
                  beacon_minor: 1,
                  rssi: -55,
                  timestamp_wall: "2026-05-26T09:00:00+08:00",
                },
              ],
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response(
      JSON.stringify({
        race_id: "duathlon-demo",
        phase: "live",
        athletes: [],
        accepted_events: [],
        raw_detections: [],
        warnings: [],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });

  render(<App />);

  expect(await screen.findByText("Receiver Health")).toBeInTheDocument();
  expect(screen.getByText("laptop-dongle-1")).toBeInTheDocument();
  expect(screen.getByText("online")).toBeInTheDocument();
  expect(screen.getByText("A001 · -55 dBm")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run failing admin test**

```bash
cd apps/admin
npm test -- --run
```

Expected: fail because receiver health client/UI does not exist.

- [ ] **Step 3: Add admin types and API client**

Modify `apps/admin/src/types.ts`:

```ts
export type ReceiverBeaconHealthView = {
  athlete_id: string;
  beacon_uuid: string;
  beacon_major: number;
  beacon_minor: number;
  rssi: number;
  timestamp_wall: string;
};

export type ReceiverHealthView = {
  receiver_id: string;
  checkpoint_id: string;
  status: "online" | "stale" | "silent";
  last_packet_wall: string | null;
  known_packets: number;
  unknown_packets: number;
  latest_known_beacons: ReceiverBeaconHealthView[];
};

export type ReceiverHealthResponse = {
  receivers: ReceiverHealthView[];
};
```

Modify `apps/admin/src/api.ts`:

```ts
import type { ReceiverHealthResponse } from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function getReceiverHealth(): Promise<ReceiverHealthResponse> {
  return requestJson<ReceiverHealthResponse>("/api/receivers/health");
}
```

If `api.ts` already has helper functions, reuse the existing helper rather than duplicating `requestJson`.

- [ ] **Step 4: Render receiver health in App**

Modify `apps/admin/src/App.tsx`:

```tsx
const [receiverHealth, setReceiverHealth] = useState<ReceiverHealthResponse | null>(null);

useEffect(() => {
  getReceiverHealth()
    .then(setReceiverHealth)
    .catch((err: Error) => setError(err.message));
}, []);
```

Render a panel in live mode:

```tsx
<section className="panel receiver-health">
  <h2>Receiver Health</h2>
  {receiverHealth?.receivers.length ? (
    receiverHealth.receivers.map((receiver) => (
      <article className={`receiver-card ${receiver.status}`} key={receiver.receiver_id}>
        <div>
          <strong>{receiver.receiver_id}</strong>
          <span>{receiver.checkpoint_id}</span>
        </div>
        <strong>{receiver.status}</strong>
        <p>Known {receiver.known_packets} · Unknown {receiver.unknown_packets}</p>
        <p>Last packet {receiver.last_packet_wall ?? "never"}</p>
        {receiver.latest_known_beacons.map((beacon) => (
          <p key={`${receiver.receiver_id}-${beacon.athlete_id}`}>
            {beacon.athlete_id} · {beacon.rssi} dBm
          </p>
        ))}
      </article>
    ))
  ) : (
    <p>No receivers reported yet.</p>
  )}
</section>
```

- [ ] **Step 5: Add minimal CSS**

Modify `apps/admin/src/styles.css`:

```css
.receiver-card {
  border: 1px solid rgba(22, 35, 31, 0.14);
  border-radius: 18px;
  margin-top: 0.75rem;
  padding: 1rem;
}

.receiver-card.online {
  border-color: #0d8f63;
}

.receiver-card.stale {
  border-color: #d48a16;
}

.receiver-card.silent {
  border-color: #b84a35;
}
```

- [ ] **Step 6: Verify admin tests and build pass**

```bash
cd apps/admin
npm test -- --run
npm run build
```

Expected: tests and build pass.

- [ ] **Step 7: Commit**

```bash
git add apps/admin/src/types.ts apps/admin/src/api.ts apps/admin/src/App.tsx apps/admin/src/App.test.tsx apps/admin/src/styles.css
git commit -m "feat: show receiver health in admin"
```

## Task 6: Documentation And Full Verification

**Files:**
- Create: `docs/acceptance/real-ble-receiver.md`
- Modify: `README.md`
- Modify: `docs/roadmap/next.md`

- [ ] **Step 1: Add acceptance checklist**

Create `docs/acceptance/real-ble-receiver.md`:

```markdown
# Real BLE Receiver Acceptance Checklist

- [ ] `tri-timing receiver-run --help` shows receiver options.
- [ ] Receiver can start with fixture race and athlete files.
- [ ] Valid iBeacon manufacturer data parses into UUID/major/minor.
- [ ] Known beacons are written to local JSONL before upload.
- [ ] Unknown beacons are ignored for race timing and counted in health.
- [ ] `POST /api/detections` stores known raw detections.
- [ ] Live detections can advance the expected route event.
- [ ] Pre-start detections do not advance route state.
- [ ] Admin UI shows receiver health and latest known beacon RSSI.
- [ ] Receiver continues logging locally if upload fails.
- [ ] Manual hardware walk/run test captures packets within roughly 5m.
```

- [ ] **Step 2: Update README**

Add to `README.md` under Local Development:

```bash
cd apps/local-core
uv run tri-timing receiver-run \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --receiver-id laptop-dongle-1 \
  --service-url http://127.0.0.1:8000 \
  --jsonl-log /tmp/tri-receiver.jsonl
```

Add the acceptance checklist link under Key Documents:

```markdown
- [Real BLE receiver acceptance checklist](docs/acceptance/real-ble-receiver.md)
```

- [ ] **Step 3: Update roadmap**

Modify `docs/roadmap/next.md` item 1 to link this spec and plan:

```markdown
Spec: [Real BLE Receiver And Detection Ingest Design](../specs/2026-05-26-real-ble-receiver-ingest-design.md)
Plan: [Real BLE Receiver And Detection Ingest Implementation Plan](../plans/2026-05-26-real-ble-receiver-ingest.md)
```

- [ ] **Step 4: Run full verification**

```bash
cd apps/local-core
uv run pytest -v
```

Expected: all local-core tests pass.

```bash
cd apps/admin
npm test -- --run
npm run build
```

Expected: admin tests and build pass.

```bash
cd apps/cloud-spectator
npm test -- --run
npm run typecheck
```

Expected: cloud spectator tests and typecheck pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/roadmap/next.md docs/acceptance/real-ble-receiver.md
git commit -m "docs: document real ble receiver acceptance"
```

## Execution Notes

- Keep receiver behavior dumb: no race decisions in scanner code.
- Keep unknown beacon observations out of `raw_detections` for now; count them in health only.
- Do not add multi-receiver synchronization in this plan.
- Do not add calibration charts in this plan.
- If physical tags do not advertise standard iBeacon frames, add a second parser test and parser branch in `tri_timing/ibeacon.py`; do not change service ingest or race engine boundaries.
