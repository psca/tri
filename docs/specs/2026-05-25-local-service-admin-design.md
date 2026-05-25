# Local Service And Admin UI Design

Date: 2026-05-25
Status: Draft for implementation planning

## Summary

Build the next MVP layer above `tri_timing`: a local Python race-day service and a TypeScript React admin UI.

The local service is the official runtime authority. It loads race config, owns the SQLite store, runs the race engine, exposes HTTP/SSE endpoints, and later hosts BLE scanner integration. The admin UI is a local operator console. It displays state and sends commands but does not make timing decisions.

No hardware is required for this phase. Synthetic detection injection must let us test race-day flow end-to-end.

## Goals

- Run a local race service from `apps/local-core`.
- Keep `tri_timing` as pure timing library code.
- Add a `tri_timing_service` package for FastAPI runtime adapters.
- Add `apps/admin` as a React/Vite TypeScript app.
- Support race start, close, state polling, live updates, and synthetic detections.
- Make this usable for no-hardware demos and future hardware integration.

## Non-Goals

- Real BLE scanner integration.
- Cloudflare spectator sync.
- Heavy setup/config editor.
- Full manual correction workflow.
- Authentication or remote multi-user admin.
- Certified race timing guarantees.

## Architecture

```text
apps/admin React UI
  -> HTTP commands
  -> SSE live stream
  -> FastAPI local service
  -> tri_timing library
  -> local SQLite canonical store
```

Package layout:

```text
apps/local-core/
  src/tri_timing/             pure timing core
  src/tri_timing_service/     FastAPI runtime service

apps/admin/
  src/                       React admin UI
```

The service and core ship from the same Python project for now. They remain separate packages so the timing core stays testable without HTTP, BLE, or UI dependencies.

## Local Service Responsibilities

The service owns:

- Process startup and settings.
- Race config and athlete loading.
- SQLite database lifecycle.
- Race phase control.
- Synthetic detection ingestion.
- Race engine calls.
- Read-model projection for admin UI.
- Server-Sent Events for live updates.

The service must not duplicate route rules. All route advancement remains in `tri_timing.engine`.

## Admin UI Responsibilities

The admin UI owns:

- Display current race phase.
- Show athletes, next expected route event, accepted events, and warnings.
- Provide Start Race and Close Race controls.
- Provide a synthetic detection panel for no-hardware testing.
- Show connection status to local service.

The admin UI must not infer pass validity or mutate local state directly.

## API

Initial endpoints:

```text
GET  /api/health
GET  /api/race/state
POST /api/race/start
POST /api/race/close
POST /api/synthetic/detection
GET  /api/events/stream
```

`GET /api/race/state` returns:

- race metadata
- phase
- athletes
- each athlete's current expected event
- accepted route events
- recent raw detections
- warnings

`POST /api/race/start` records `race_start_at` and moves the race to `live`.

`POST /api/race/close` moves the race to `closed` and stops automatic route advancement.

`POST /api/synthetic/detection` accepts a beacon or athlete identity, checkpoint ID, RSSI, timestamp, and optional repeat count. It writes raw detections through the same ingestion path that a real scanner will use later.

`GET /api/events/stream` emits SSE messages when state changes. Polling remains acceptable as fallback.

## State Model

Race phases:

```text
pre_start
live
closed
```

This phase can store phase metadata in SQLite using append-only facts or a small service metadata table. Race decisions must still be rebuildable from config plus stored facts.

For MVP, the service can maintain an in-memory projection and rebuild it on startup from SQLite.

## Error Handling

- Invalid config prevents service startup with a clear error.
- Unknown athlete/beacon synthetic detections return HTTP 400.
- Starting an already live race is idempotent and returns current state.
- Closing an already closed race is idempotent and returns current state.
- SSE clients can disconnect without affecting race state.

## Testing

Python tests cover:

- FastAPI health/state endpoints.
- Start/close phase transitions.
- Synthetic detection ingestion into core engine.
- SSE event broadcaster behavior at unit level.

Admin tests cover:

- API client state parsing.
- Race controls call expected endpoints.
- Synthetic detection form sends expected payload.
- Main dashboard renders phase, athletes, and accepted events.

End-to-end manual check:

1. Start local service with fixture config.
2. Start admin UI.
3. Click Start Race.
4. Submit synthetic detections.
5. Observe accepted route event and live state update.

