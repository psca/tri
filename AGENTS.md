# Repository Guidelines

## Project Structure & Module Organization

This repository is a monorepo for a BLE-assisted triathlon/duathlon timing system.

- `apps/local-core/` contains the Python timing authority, CLI, tests, fixtures, `pyproject.toml`, and `uv.lock`.
- `apps/local-core/src/tri_timing/` contains the Python package.
- `apps/local-core/tests/` contains pytest coverage and fixtures.
- `docs/specs/` contains approved design specs and presentation material.
- `docs/plans/` contains implementation plans.
- `docs/acceptance/` contains acceptance checklists.
- Future frontend/cloud code should use clear top-level directories such as `apps/admin/`, `apps/spectator/`, and `infra/cloudflare/`.

Keep source files focused by responsibility: config loading, route compilation, storage, detection, engine, scanner adapters, and CLI should remain separate modules.

## Build, Test, and Development Commands

Python uses `uv` for environment and command execution. For the local core, use:

```bash
cd apps/local-core
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay --race tests/fixtures/race.yaml --athletes tests/fixtures/athletes.csv --output /tmp/tri-timing-result.json
```

For docs-only changes, verify links and read the rendered Markdown/HTML locally.

Do not run Python commands directly when `uv run ...` works; this keeps dependencies and console scripts consistent with `uv.lock`.

## Coding Style & Naming Conventions

Use Python 3.11+ for local timing code. Prefer small modules, dataclasses for explicit data shapes, and deterministic functions for replayable logic.

Naming examples:

- Python modules: `snake_case.py`
- Tests: `apps/local-core/tests/test_<module>.py`
- Route events: `run1_lap1_complete`, `t1_out_bike_start`
- Config files: `race.yaml`, `athletes.csv`, `receivers.yaml`

Avoid putting race-state or timing logic in React. UI should display projections and send operator commands only.

## Testing Guidelines

Use `pytest` via `uv run pytest` for Python. Tests should cover replay determinism, start-grace suppression, RSSI pass detection, ordered route advancement, manual correction behavior, and SQLite append-only storage.

Prefer fixture-driven tests using `apps/local-core/tests/fixtures/`. Name tests by behavior, e.g. `test_start_grace_blocks_route_advancement`.

## Commit & Pull Request Guidelines

Current history uses Conventional Commit style:

```text
docs: add ble timing mvp design
```

Use short imperative commit messages with prefixes such as `docs:`, `feat:`, `fix:`, `test:`, and `chore:`.

Pull requests should include a summary, test evidence, affected docs/specs, and screenshots for UI changes. For behavior changes, explain race-day impact and any replay/audit implications.

## Architecture Notes

The local Python service is the official timing authority. SQLite is canonical. Cloudflare is spectator/read-only backup for MVP. BLE detections are evidence; accepted route events and manual corrections are append-only facts.
