# Tri Timing

BLE-assisted timing system for friendly triathlon and duathlon competitions.

The project is currently in planning/design. The intended MVP is a local-first timing setup where athletes wear configurable iBeacon wristbands, a laptop with a USB BLE dongle acts as the race authority, and Cloudflare provides a read-only spectator dashboard and backup sync.

## Current Status

Implemented so far:

- MVP design spec.
- HTML slide deck summarizing the spec.
- Local-core implementation plan.
- Contributor guide.

No executable application code exists yet.

## Key Documents

- [MVP design spec](docs/superpowers/specs/2026-05-25-ble-triathlon-timing-mvp-design.md)
- [HTML slide deck](docs/superpowers/specs/2026-05-25-ble-triathlon-timing-mvp-slides.html)
- [Local-core implementation plan](docs/superpowers/plans/2026-05-25-ble-timing-local-core.md)
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

## Planned Local Development

The first implementation target is the Python local core:

```bash
python -m pytest -v
python -m tri_timing.cli synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
```

These commands will become valid once the local-core plan is implemented.

## Branches

Active development is on `development`.
