# Repository Guidelines

## Project Structure & Module Organization

This repository is a monorepo for a BLE-assisted triathlon/duathlon timing system.

- `apps/local-core/` contains the Python timing authority, CLI, tests, fixtures, `pyproject.toml`, and `uv.lock`.
- `apps/local-core/src/tri_timing/` contains the Python package.
- `apps/local-core/src/tri_timing_service/` contains the local FastAPI timing authority runtime.
- `apps/local-core/tests/` contains pytest coverage and fixtures.
- `apps/admin/` contains the local React/Vite admin shell.
- `apps/cloud-spectator/` contains the Cloudflare Worker, D1 migrations, and spectator API tests.
- `docs/specs/` contains approved design specs and presentation material.
- `docs/plans/` contains implementation plans.
- `docs/acceptance/` contains acceptance checklists.
- Future frontend/cloud code should use clear top-level directories such as `apps/admin/`, `apps/spectator/`, `apps/cloud-spectator/`, and `infra/cloudflare/`.

Keep source files focused by responsibility: config loading, route compilation, storage, detection, engine, scanner adapters, and CLI should remain separate modules.

## Build, Test, and Development Commands

Python uses `uv` for environment and command execution. For the local core, use:

```bash
cd apps/local-core
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay --race tests/fixtures/race.yaml --athletes tests/fixtures/athletes.csv --output /tmp/tri-timing-result.json
uv run tri-timing receiver-run --race tests/fixtures/race.yaml --athletes tests/fixtures/athletes.csv --receiver-id laptop-dongle-1 --service-url http://127.0.0.1:8000 --jsonl-log /tmp/tri-receiver.jsonl
uv run uvicorn tri_timing_service.app:create_app --factory --reload
```

Local service commands run from `apps/local-core`.

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

Use `pytest` via `uv run pytest` for Python. Tests should cover replay determinism, start-grace suppression, RSSI pass detection, receiver ingest/health behavior, ordered route advancement, manual correction behavior, and SQLite append-only storage.

Prefer fixture-driven tests using `apps/local-core/tests/fixtures/`. Name tests by behavior, e.g. `test_start_grace_blocks_route_advancement`.

## Commit & Pull Request Guidelines

Current history uses Conventional Commit style:

```text
docs: add ble timing mvp design
```

Use short imperative commit messages with prefixes such as `docs:`, `feat:`, `fix:`, `test:`, and `chore:`.

Pull requests should include a summary, test evidence, affected docs/specs, and screenshots for UI changes. For behavior changes, explain race-day impact and any replay/audit implications.

## Architecture Notes

The Python receiver is a dumb BLE collector: parse iBeacon packets, write JSONL, and upload detections. The local Python service is the official timing authority. `tri_timing` is library code, and `tri_timing_service` is the local FastAPI runtime adapter. SQLite is canonical. Cloudflare is spectator/read-only backup for MVP, and D1 is a derived read model. Cloud sync must be idempotent and must not block local timing when the network or ingest endpoint is unavailable. BLE detections are evidence; accepted route events and manual corrections are append-only facts. Manual corrections must not edit or delete accepted events; derive corrected state through review projection.
