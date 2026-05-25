# Tri Timing Local Core

Python local timing authority for the BLE-assisted race system.

This package owns config loading, route compilation, SQLite append-only storage, RSSI pass detection, race-state advancement, scanner adapter boundaries, and the synthetic replay CLI.

`tri_timing` is the pure timing library. `tri_timing_service` is the local FastAPI runtime adapter that exposes the library through HTTP/SSE and process lifecycle commands for race-day operation.

## Development

Run commands from this directory:

```bash
uv sync --dev
uv run pytest -v
uv run tri-timing synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
uv run uvicorn tri_timing_service.app:create_app --factory --reload
```

Expected replay output:

```text
accepted 1 route event
```

## Layout

```text
src/tri_timing/      package source
src/tri_timing_service/
                     local FastAPI runtime adapter
tests/               pytest suite and fixtures
tests/fixtures/      sample race and athlete configs
```
