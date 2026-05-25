# Tri Timing

BLE-assisted timing system for friendly triathlon and duathlon competitions.

The current implementation is a local-first Python timing core. The intended MVP uses configurable iBeacon wristbands, a laptop with a USB BLE dongle as the race authority, and later Cloudflare sync for a read-only spectator dashboard and backup storage.

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

## Key Documents

- [MVP design spec](docs/superpowers/specs/2026-05-25-ble-triathlon-timing-mvp-design.md)
- [HTML slide deck](docs/superpowers/specs/2026-05-25-ble-triathlon-timing-mvp-slides.html)
- [Local-core implementation plan](docs/superpowers/plans/2026-05-25-ble-timing-local-core.md)
- [Local-core acceptance checklist](docs/local-core-acceptance.md)
- [Contributor guide](AGENTS.md)

## Planned Architecture

```text
BLE iBeacon wristband
  -> USB BLE dongle
  -> Python local race service
  -> SQLite canonical store
  -> local React admin UI
  -> queued Cloudflare sync
  -> spectator dashboard / R2 backup
```

Core rules:

- Local Python service is the official timing authority.
- SQLite is canonical.
- Cloudflare is read-only/spectator for MVP.
- BLE detections are evidence, not timing facts.
- Route advancement and manual corrections are append-only facts.

## Local Development

Python uses `uv` for environment and command execution:

```bash
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
```

Expected replay output:

```text
accepted 1 route event
```

## Branches

Active development is on `development`.
