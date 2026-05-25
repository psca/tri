# Cloud Spectator Sync Design

Date: 2026-05-25
Status: Draft for implementation planning

## Summary

Build the cloud layer for the BLE timing MVP as a read-only spectator system. The local Python race service remains the timing authority. Cloudflare receives queued race updates from the local service, stores a spectator read model in D1, optionally writes backup payloads to R2, and exposes public read APIs for friends to follow the race.

The cloud must tolerate phone hotspot drops. If the internet is unavailable, the local service continues timing normally and keeps pending sync items in SQLite. When connectivity returns, it uploads the backlog in order. Cloud state can lag, but it must not corrupt local timing.

## Goals

- Add a Cloudflare Worker app for ingest and spectator read APIs.
- Use D1 as the public read model for race state, leaderboard, and event history.
- Use R2 for optional raw sync payload backup/export redundancy.
- Extend the local service sync outbox into an HTTP publisher.
- Make sync idempotent so retries are safe.
- Keep cloud strictly read-only from the race-timing perspective.
- Support synthetic local events so the whole cloud flow can be tested before hardware arrives.

## Non-Goals

- Cloud race authority or cloud-side race engine.
- Remote admin control, manual corrections, or race setup editing.
- Real-time WebSockets for spectators in the first version.
- Uploading every BLE raw detection by default.
- Certified timing guarantees.
- Multi-race public discovery or user accounts.

## Architecture

```text
local FastAPI service
  -> SQLite sync_outbox
  -> local sync publisher with retry
  -> Cloudflare Worker ingest API
  -> D1 spectator read model
  -> optional R2 backup object
  -> public spectator JSON APIs
```

Repository layout:

```text
apps/
  cloud-spectator/        Cloudflare Worker, D1 migrations, Worker tests
apps/local-core/
  src/tri_timing/         canonical SQLite store and sync outbox
  src/tri_timing_service/ local runtime and sync publisher
```

Cloudflare product choices:

- Workers: HTTP ingest and public spectator APIs.
- D1: small relational read model for latest race state and ordered event history.
- R2: optional append-only backup objects for sync payloads and future exports.
- Queues: not needed for MVP. Add later if cloud-side processing becomes heavier.

## Data Ownership

Local SQLite is canonical. Cloud D1 is a derived read model.

Accepted route events, race snapshots, and receiver health updates are facts emitted by the local service. The cloud Worker validates envelope shape, checks auth, deduplicates by idempotency key, then upserts D1 rows.

The cloud must never infer route advancement. It displays the latest local truth it received.

## Sync Payloads

Each uploaded item uses a common envelope:

```json
{
  "idempotency_key": "duathlon-001:42",
  "payload_hash": "sha256-hex",
  "race_id": "duathlon-001",
  "local_sequence_number": 42,
  "type": "accepted_route_event",
  "created_at": "2026-05-25T09:15:03.240Z",
  "payload": {}
}
```

Initial payload types:

- `race_state_snapshot`: compact current race phase, athletes, next events, accepted events count, generated timestamp.
- `accepted_route_event`: one accepted route event emitted by the local race engine.
- `receiver_health_snapshot`: receiver online/offline state, last packet timestamp, packet rate, recent warning count.

Raw BLE detections are intentionally excluded from the default cloud path. They stay local. Later, the operator can export a full raw-data archive to R2 after the race.

## D1 Read Model

Initial D1 tables:

```text
sync_items
- idempotency_key TEXT PRIMARY KEY
- race_id TEXT NOT NULL
- local_sequence_number INTEGER NOT NULL
- type TEXT NOT NULL
- payload_hash TEXT NOT NULL
- received_at TEXT NOT NULL

races
- race_id TEXT PRIMARY KEY
- name TEXT
- phase TEXT NOT NULL
- updated_at TEXT NOT NULL
- snapshot_json TEXT NOT NULL

accepted_route_events
- race_id TEXT NOT NULL
- local_sequence_number INTEGER NOT NULL
- athlete_id TEXT NOT NULL
- route_event_id TEXT NOT NULL
- checkpoint_id TEXT NOT NULL
- event_time_wall TEXT NOT NULL
- confidence TEXT NOT NULL
- PRIMARY KEY (race_id, local_sequence_number)

receiver_health
- race_id TEXT NOT NULL
- receiver_id TEXT NOT NULL
- checkpoint_id TEXT NOT NULL
- status TEXT NOT NULL
- last_packet_at TEXT
- packet_rate REAL
- updated_at TEXT NOT NULL
- PRIMARY KEY (race_id, receiver_id)
```

Leaderboard can be computed from `snapshot_json` initially. If that becomes awkward, add a projected `athlete_states` table later.

## API

Authenticated local ingest:

```text
POST /api/ingest
```

The local service sends one sync item per request for the first version. The Worker uses a shared secret bearer token. Invalid auth returns `401`. Duplicate idempotency keys with the same hash return success. Duplicate keys with a different hash return `409`.

Public spectator APIs:

```text
GET /api/races/:raceId/state
GET /api/races/:raceId/events
GET /api/races/:raceId/leaderboard
```

These endpoints are read-only and cacheable for a short period. They can power either a future spectator React app or a simple static page.

## Local Publisher

The local service owns a background sync loop:

1. Read pending `sync_outbox` rows ordered by `local_sequence_number`.
2. POST the next item to Cloudflare with timeout and bearer token.
3. Mark success as synced.
4. On failure, increment attempts, store last error, and retry later with backoff.
5. Never block timing, race start, or admin commands on cloud sync.

The existing `sync_outbox` table should be extended with `synced_at` and enough status transitions to distinguish `pending`, `in_flight`, `synced`, and `failed_retryable`.

## Failure Handling

- Internet down: local race continues; outbox grows.
- Worker down: publisher retries; local timing unaffected.
- Duplicate upload: Worker returns success if hash matches.
- Payload conflict: Worker returns `409`; local row remains unsynced with last error for operator review.
- R2 write failure: D1 ingest can still succeed. R2 backup is best-effort for MVP.
- Cloud stale: spectator APIs should include `updated_at` so viewers know data age.

## Security

- Ingest requires `Authorization: Bearer <secret>`.
- Public endpoints expose only spectator-safe race state.
- Do not upload raw BLE logs by default.
- Do not store secrets in source or Wrangler config.
- CORS is limited to configured spectator/admin origins when a browser client is added.

## Testing

Local Python tests:

- Outbox pending/synced status updates.
- Publisher handles success, network failure, retryable HTTP errors, and hash conflict.
- Publisher does not block race runtime.

Worker tests:

- Ingest rejects missing auth.
- Ingest accepts valid event payloads.
- Duplicate same-hash ingest is idempotent.
- Duplicate different-hash ingest returns conflict.
- Public state/events endpoints return projected D1 data.

Manual no-hardware check:

1. Start local service with fixture config.
2. Start cloud Worker locally with D1.
3. Start race and send synthetic detections.
4. Observe local outbox rows marked synced.
5. Query public state/events APIs and confirm accepted events appear.
