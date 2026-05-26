# Next Project Roadmap

This is the living queue for near-term work. Keep it short, ordered by risk reduction, and update it when hardware tests change assumptions.

## Current Position

The software can run a local race authority, simulate detections, ingest real iBeacon packets from the Python receiver path, advance ordered route state, review timelines, apply append-only manual corrections, restart cleanly, and sync timing facts toward Cloudflare.

Real hardware validation is still pending. The next work should reduce calibration and race-day workflow risk without adding heavy new product scope.

## Completed Recently

### Real BLE Receiver + Local Detection Ingest + Minimal Receiver Health

Spec: [Real BLE Receiver And Detection Ingest Design](../specs/2026-05-26-real-ble-receiver-ingest-design.md)  
Plan: [Real BLE Receiver And Detection Ingest Implementation Plan](../plans/2026-05-26-real-ble-receiver-ingest.md)  
Acceptance: [Real BLE Receiver Acceptance Checklist](../acceptance/real-ble-receiver.md)

Delivered:

- Python `bleak` receiver command: `tri-timing receiver-run`.
- iBeacon parser for UUID/major/minor/measured power.
- Local JSONL fallback logging before upload.
- Receiver upload batching, retry, cancellation flush, and bounded backlog.
- `POST /api/detections` ingest endpoint.
- Known beacon raw detection persistence and pass detector feed.
- Unknown iBeacon health counting without storing race timing evidence.
- Receiver startup validation for configured `receiver_id`.
- Receiver health states: `silent`, `online`, `stale`.
- Admin receiver health panel with polling.

## Priority Queue

### 1. Detection Replay / Calibration Tooling

**Purpose:** tune RSSI thresholds using captured hardware data.

- Read raw detections from JSONL or SQLite.
- Replay through detection policies.
- Show candidate windows, strongest RSSI, packet count, confidence, and accepted/suppressed decisions.
- Compare policy settings without rerunning the physical test.

Success means a hardware walk/run test can produce actionable threshold changes.

### 2. Race-Day Dry Run + Acceptance Hardening

**Purpose:** make the operator workflow repeatable before a real event.

- Script a deterministic local dry run.
- Start service, start race, inject/simulate detections, apply correction, restart, verify state.
- Document race-day checklist: pre-race beacon check, receiver check, start procedure, review procedure, export/sync check.

Success means the full workflow can be rehearsed without guessing.

### 3. Cloud Spectator Polish

**Purpose:** improve the remote viewing experience after the local authority is reliable.

- Public race page.
- Split/leaderboard display.
- Correction-aware read model.
- Cloud sync health/status visibility.

Do not prioritize this over local BLE reliability.

### 4. Multi-Receiver / Transition Accuracy

**Purpose:** improve timing confidence only if single-receiver testing shows gaps.

- Multiple receivers per checkpoint.
- Per-receiver packet windows.
- RSSI comparison and first-hit/strongest-hit policies.
- Transition in/out disambiguation.

Defer until one receiver has been tested with real hardware.

## Near-Term Recommendation

Write the next spec/plan for **Detection Replay / Calibration Tooling**. Keep it narrow: consume the JSONL/SQLite data we now produce, replay detection policy decisions, and make threshold tuning practical once the hardware arrives.
