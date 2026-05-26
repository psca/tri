# Real BLE Receiver And Detection Ingest Design

Date: 2026-05-26
Status: Draft for implementation planning

## Summary

Build the missing hardware bridge between configurable BLE/iBeacon wristbands and the local timing authority. The receiver process runs on the race laptop, scans BLE advertisements with `bleak`, filters known athlete beacons, writes a local JSONL fallback log, and posts normalized detections to the local FastAPI service. The service accepts real detections, stores them as raw evidence, feeds the existing RSSI pass detector, advances the race engine, and exposes minimal receiver health to the admin UI.

This phase is deliberately narrow. It should prove that one laptop, one BLE dongle, and real beacon tags can produce useful timing facts. It should not solve multi-receiver timing, advanced calibration, cloud spectator polish, or transition automation beyond the existing detection policies.

## Goals

- Add a real Python BLE scanner path using `bleak`.
- Parse iBeacon advertisements into UUID, major, minor, RSSI, and timestamps.
- Filter observations against configured athletes.
- Persist every known-beacon observation to local receiver JSONL before upload.
- Add local service detection ingest: `POST /api/detections`.
- Store ingested detections in SQLite and run them through existing route/detector logic.
- Track minimal receiver health for admin visibility.
- Add admin receiver health display.
- Keep the current synthetic detection path working for demos and tests.

## Non-Goals

- Multi-receiver synchronization.
- Exact chip-timing precision.
- Phone-as-beacon support.
- Beacon configuration over BLE.
- Automatic threshold tuning.
- Rich calibration charts.
- Cloud spectator UI changes.
- Authentication for the local receiver API.

## Architecture

```text
BLE iBeacon wristband
  -> Python receiver process
  -> local JSONL fallback log
  -> POST /api/detections
  -> FastAPI local service
  -> SQLite raw_detections
  -> PassDetector per athlete/route event
  -> RaceEngine route decision
  -> accepted_route_events
  -> admin SSE/state/receiver health
```

The receiver remains dumb. It does not decide whether a pass is valid and does not advance athlete state. It only parses, filters, logs, and uploads observations.

The local service remains the timing authority. It validates receiver/checkpoint/beacon identity, stores raw evidence, applies detection policies, advances route state only when rules allow it, and publishes admin updates.

## Components

### iBeacon Parser

Create a small parser module in `tri_timing` that can decode iBeacon manufacturer data without depending on `bleak`. This makes parser behavior testable without hardware.

Expected iBeacon manufacturer payload shape:

```text
Apple company id: 0x004c
payload bytes:
  0: 0x02
  1: 0x15
  2-17: UUID
  18-19: major uint16 big-endian
  20-21: minor uint16 big-endian
  22: measured power signed int8
```

The parser returns:

```python
IBeaconAdvertisement(
    uuid="11111111-1111-1111-1111-111111111111",
    major=1,
    minor=2,
    measured_power=-59,
)
```

Non-iBeacon payloads return `None`.

### Receiver Process

Add a receiver runner under `tri_timing.receiver` and expose it through the existing `tri-timing` CLI:

```bash
uv run tri-timing receiver-run \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --receiver-id laptop-dongle-1 \
  --service-url http://127.0.0.1:8000 \
  --jsonl-log /tmp/tri-receiver.jsonl
```

The process:

- loads race and athlete config;
- validates the receiver ID exists and derives its checkpoint ID;
- starts `bleak.BleakScanner`;
- parses iBeacon manufacturer data;
- ignores unknown beacons but counts them for health/debug logs;
- writes known-beacon observations to JSONL before upload;
- posts batches to `/api/detections`;
- retries failed uploads without deleting the local log;
- prints concise operational status.

### Detection Ingest API

Add:

```text
POST /api/detections
GET  /api/receivers/health
```

`POST /api/detections` accepts:

```json
{
  "receiver_id": "laptop-dongle-1",
  "detections": [
    {
      "beacon_uuid": "11111111-1111-1111-1111-111111111111",
      "beacon_major": 1,
      "beacon_minor": 2,
      "rssi": -61,
      "timestamp_wall": "2026-05-26T09:00:00+08:00",
      "timestamp_monotonic": 12345.67
    }
  ]
}
```

The service derives `checkpoint_id` from receiver config. It derives `athlete_id` from beacon UUID/major/minor. Known detections are stored as raw evidence. Unknown beacons are not stored as timing evidence but are counted in receiver health.

Response:

```json
{
  "stored": 1,
  "ignored_unknown": 0,
  "accepted_events": [
    {
      "athlete_id": "A001",
      "route_event_id": "run1_lap1_complete"
    }
  ]
}
```

### Live Detection State

The current synthetic path builds a detector per synthetic request. Real ingest needs persistent detectors.

The runtime should keep:

```python
_live_detectors: dict[tuple[str, str], PassDetector]
```

Key:

```text
athlete_id + expected route_event_id
```

When a known detection arrives:

1. Store raw detection.
2. Update receiver health.
3. If race phase is not `live`, stop after storage/health.
4. Find athlete's current expected route event.
5. If receiver checkpoint does not match expected checkpoint, ignore for route advancement.
6. Feed the matching detector using that route event's detection policy.
7. If a candidate closes, call `RaceEngine.apply_pass`.
8. If accepted, append accepted route event and publish state.

Synthetic detections should reuse the same ingest path where practical so real and fake detections do not drift.

### Receiver Health

The service tracks receiver health in memory from ingest traffic:

```ts
type ReceiverHealthView = {
  receiver_id: string;
  checkpoint_id: string;
  status: "online" | "stale" | "silent";
  last_packet_wall: string | null;
  known_packets: number;
  unknown_packets: number;
  latest_known_beacons: Array<{
    athlete_id: string;
    beacon_uuid: string;
    beacon_major: number;
    beacon_minor: number;
    rssi: number;
    timestamp_wall: string;
  }>;
};
```

Status rule for MVP:

- `online`: packet seen within last 10 seconds.
- `stale`: packet seen, but older than 10 seconds.
- `silent`: no packet since service start.

This is intentionally volatile. SQLite remains canonical for race facts, not receiver health.

### Admin UI

Add a small receiver health section to the existing admin app:

- receiver ID and checkpoint;
- online/stale/silent status;
- last packet time;
- known/unknown packet counts;
- latest known beacon rows with athlete, RSSI, and timestamp.

This should be useful during hardware testing without becoming a full calibration UI.

## Error Handling

- Unknown receiver ID returns HTTP 400.
- Invalid checkpoint mapping fails startup through existing config validation.
- Unknown beacons are counted but not stored as athlete raw detections.
- Bad detection payloads return HTTP 422 or 400 before modifying state.
- Receiver upload failures are logged locally and retried in later batches.
- JSONL writes happen before POST so network loss does not lose raw observations.
- BLE scanner exceptions should stop the receiver process with a clear error instead of silently running.

## Testing

Python tests:

- iBeacon parser decodes valid manufacturer data.
- iBeacon parser ignores non-iBeacon data.
- receiver filter maps configured beacons to athletes.
- JSONL writer writes one line per known detection.
- receiver API client posts batches and surfaces failed uploads.
- `POST /api/detections` stores known raw detections.
- ingest feeds detector and creates accepted route events when enough packets arrive.
- pre-start detections store raw evidence but do not advance route state.
- unknown beacons increment health but do not create raw detections.
- receiver health returns online/stale/silent states.

Admin tests:

- receiver health is fetched and rendered.
- SSE or refresh updates receiver health display if implemented through state events.
- existing live/review/manual correction tests continue to pass.

Manual hardware check:

1. Start local service.
2. Start admin UI.
3. Start receiver process.
4. Move a configured beacon near the laptop.
5. Confirm receiver health changes to `online`.
6. Start race.
7. Walk/run past receiver.
8. Confirm raw detections and accepted route events appear.
9. Disconnect network/service temporarily and confirm JSONL continues.

## Open Assumptions

- The purchased tags advertise standard iBeacon manufacturer data.
- UUID/major/minor can be configured or at least read consistently.
- One receiver maps to one checkpoint for MVP.
- The receiver process runs on the same laptop or LAN as the local service.
- Local service auth is unnecessary for MVP because this is a local race network.

If the tags do not advertise standard iBeacon frames, the parser module becomes the place to add vendor-specific parsing without changing race logic.
