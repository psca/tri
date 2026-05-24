# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains planning and specification documents for a BLE-assisted triathlon/duathlon timing system.

- `docs/superpowers/specs/` contains approved design specs and presentation material.
- `docs/superpowers/plans/` contains implementation plans.
- Planned Python local core paths are `src/tri_timing/` and `tests/`.
- Planned frontend/cloud code should use clear top-level directories such as `web/` for React admin/spectator UI and `cloudflare/` or `workers/` for Workers code.

Keep source files focused by responsibility: config loading, route compilation, storage, detection, engine, scanner adapters, and CLI should remain separate modules.

## Build, Test, and Development Commands

Python uses `uv` for environment and command execution. For the local core, use:

```bash
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay --race tests/fixtures/race.yaml --athletes tests/fixtures/athletes.csv --output /tmp/tri-timing-result.json
```

For docs-only changes, verify links and read the rendered Markdown/HTML locally.

## Coding Style & Naming Conventions

Use Python 3.11+ for local timing code. Prefer small modules, dataclasses or Pydantic models for explicit data shapes, and deterministic functions for replayable logic.

Naming examples:

- Python modules: `snake_case.py`
- Tests: `tests/test_<module>.py`
- Route events: `run1_lap1_complete`, `t1_out_bike_start`
- Config files: `race.yaml`, `athletes.csv`, `receivers.yaml`

Avoid putting race-state or timing logic in React. UI should display projections and send operator commands only.

## Testing Guidelines

Use `pytest` via `uv run pytest` for Python. Tests should cover replay determinism, start-grace suppression, RSSI pass detection, ordered route advancement, manual correction behavior, and SQLite append-only storage.

Prefer fixture-driven tests using `tests/fixtures/`. Name tests by behavior, e.g. `test_start_grace_blocks_route_advancement`.

## Commit & Pull Request Guidelines

Current history uses Conventional Commit style:

```text
docs: add ble timing mvp design
```

Use short imperative commit messages with prefixes such as `docs:`, `feat:`, `fix:`, `test:`, and `chore:`.

Pull requests should include a summary, test evidence, affected docs/specs, and screenshots for UI changes. For behavior changes, explain race-day impact and any replay/audit implications.

## Architecture Notes

The local Python service is the official timing authority. SQLite is canonical. Cloudflare is spectator/read-only backup for MVP. BLE detections are evidence; accepted route events and manual corrections are append-only facts.
