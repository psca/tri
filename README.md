# Tri Timing

BLE-assisted timing system for friendly triathlon and duathlon competitions.

The current implementation is a local-first timing system in a monorepo layout. The intended MVP uses configurable iBeacon wristbands, a laptop with a USB BLE dongle as the race authority, local admin controls, and Cloudflare sync for a read-only spectator dashboard and backup storage.

## Current Status

Implemented so far:

- MVP design spec.
- HTML slide deck summarizing the spec.
- Local-core implementation plan.
- Local-core acceptance checklist.
- Contributor guide.
- Python package scaffold using `uv`.
- Config loading for race YAML and athlete CSV.
- Ordered route compiler with laps and transitions.
- SQLite append-only event store with sync outbox.
- RSSI pass detector with cooldown/stale-window handling.
- Race engine for start grace, expected route advancement, duplicate suppression, and finish state.
- Scanner adapter boundary and synthetic replay CLI.
- Real iBeacon parser and Python `bleak` receiver CLI.
- Receiver JSONL fallback logging, upload retry, and startup validation.
- Local detection ingest API and receiver health status.
- Local FastAPI service runtime adapter.
- Local React/Vite admin shell.
- Admin receiver health panel with polling.
- Retrying cloud sync publisher for accepted timing facts.
- Cloudflare Worker spectator API with authenticated ingest, D1 migrations, and public read endpoints.
- Manual review/correction design and implementation.

## Key Documents

- [MVP design spec](docs/specs/2026-05-25-ble-triathlon-timing-mvp-design.md)
- [HTML slide deck](docs/specs/2026-05-25-ble-triathlon-timing-mvp-slides.html)
- [Local-core implementation plan](docs/plans/2026-05-25-ble-timing-local-core.md)
- [Cloud spectator sync implementation plan](docs/plans/2026-05-25-cloud-spectator-sync.md)
- [Real BLE receiver design](docs/specs/2026-05-26-real-ble-receiver-ingest-design.md)
- [Real BLE receiver implementation plan](docs/plans/2026-05-26-real-ble-receiver-ingest.md)
- [Local-core acceptance checklist](docs/acceptance/local-core.md)
- [Cloud spectator acceptance checklist](docs/acceptance/cloud-spectator.md)
- [Manual review/corrections acceptance checklist](docs/acceptance/manual-review-corrections.md)
- [Real BLE receiver acceptance checklist](docs/acceptance/real-ble-receiver.md)
- [Next project roadmap](docs/roadmap/next.md)
- [Contributor guide](AGENTS.md)

## Repository Layout

```text
apps/
  local-core/      Python timing authority, tests, and CLI
  admin/           Local React admin shell
  cloud-spectator/ Cloudflare Worker, D1 migrations, and spectator API tests
docs/
  specs/           Design specs and slide decks
  plans/           Implementation plans
  acceptance/      Acceptance checklists
```

## Planned Architecture

```text
BLE iBeacon wristband
  -> USB BLE dongle
  -> Python receiver CLI
  -> JSONL fallback log
  -> Python local race service
  -> SQLite canonical store
  -> local React admin UI
  -> retrying Cloudflare sync
  -> D1 spectator read model / R2 backup
```

Core rules:

- Local Python service is the official timing authority.
- `tri_timing` is the pure timing library; `tri_timing_service` is the local FastAPI runtime adapter.
- SQLite is canonical.
- Cloudflare is read-only/spectator for MVP, with D1 as a derived read model.
- Cloud sync must be idempotent and must not block local race timing.
- BLE detections are evidence, not timing facts.
- Route advancement and manual corrections are append-only facts.

## Local Development

Python uses `uv` for environment and command execution:

```bash
cd apps/local-core
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
uv run tri-timing receiver-run \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --receiver-id laptop-dongle-1 \
  --service-url http://127.0.0.1:8000 \
  --jsonl-log /tmp/tri-receiver.jsonl
uv run uvicorn tri_timing_service.app:create_app --factory --reload
```

Expected replay output:

```text
accepted 1 route event
```

Admin UI commands run from `apps/admin`:

```bash
cd apps/admin
npm install
npm run dev
npm test
npm run build
```

Cloud spectator commands run from `apps/cloud-spectator`:

```bash
cd apps/cloud-spectator
npm install
npm test -- --run
npm run typecheck
npm run dev
```

## Branches

Active development is on `development`.
