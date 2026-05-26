# Next Project Roadmap

This is the living queue for near-term work. Keep it short, ordered by risk reduction, and update it when hardware tests change assumptions.

## Current Position

The software can run a local race authority, simulate detections, advance ordered route state, review timelines, apply append-only manual corrections, restart cleanly, and sync timing facts toward Cloudflare. The missing bridge is real BLE packet capture from hardware.

## Priority Queue

### 1. Real BLE Receiver + Local Detection Ingest + Minimal Receiver Health

**Purpose:** connect actual beacon hardware to the local timing authority.

Spec: [Real BLE Receiver And Detection Ingest Design](../specs/2026-05-26-real-ble-receiver-ingest-design.md)  
Plan: [Real BLE Receiver And Detection Ingest Implementation Plan](../plans/2026-05-26-real-ble-receiver-ingest.md)

Bundle these together because they form one end-to-end hardware path:

- Python `bleak` scanner loop.
- iBeacon advertisement parser for UUID/major/minor/RSSI.
- Known beacon filtering from `athletes.csv`.
- Receiver config for `receiver_id` and `checkpoint_id`.
- Local JSONL fallback log.
- `POST /api/detections` single/batch ingest endpoint.
- Raw detection persistence and pass detector feed.
- Minimal admin receiver health: last packet, packet rate, known/unknown beacons, latest RSSI.

Success means one laptop can see real beacons, record raw detections, and advance race state.

### 2. Detection Replay / Calibration Tooling

**Purpose:** tune RSSI thresholds using captured hardware data.

- Read raw detections from JSONL or SQLite.
- Replay through detection policies.
- Show candidate windows, strongest RSSI, packet count, confidence, and accepted/suppressed decisions.
- Compare policy settings without rerunning the physical test.

Success means a hardware walk/run test can produce actionable threshold changes.

### 3. Race-Day Dry Run + Acceptance Hardening

**Purpose:** make the operator workflow repeatable before a real event.

- Script a deterministic local dry run.
- Start service, start race, inject/simulate detections, apply correction, restart, verify state.
- Document race-day checklist: pre-race beacon check, receiver check, start procedure, review procedure, export/sync check.

Success means the full workflow can be rehearsed without guessing.

### 4. Cloud Spectator Polish

**Purpose:** improve the remote viewing experience after the local authority is reliable.

- Public race page.
- Split/leaderboard display.
- Correction-aware read model.
- Cloud sync health/status visibility.

Do not prioritize this over local BLE reliability.

### 5. Multi-Receiver / Transition Accuracy

**Purpose:** improve timing confidence only if single-receiver testing shows gaps.

- Multiple receivers per checkpoint.
- Per-receiver packet windows.
- RSSI comparison and first-hit/strongest-hit policies.
- Transition in/out disambiguation.

Defer until one receiver has been tested with real hardware.

## Near-Term Recommendation

Write the next spec/plan for **Real BLE Receiver + Local Detection Ingest + Minimal Receiver Health**. Keep it narrow: prove live BLE data can enter the system and produce useful timing facts before expanding UI or cloud scope.
