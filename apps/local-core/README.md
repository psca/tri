# Tri Timing Local Core

Python local timing authority for the BLE-assisted race system.

This package owns config loading, route compilation, SQLite append-only storage, RSSI pass detection, race-state advancement, scanner adapter boundaries, and the synthetic replay CLI.

## Development

Run commands from this directory:

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

## Layout

```text
src/tri_timing/      package source
tests/               pytest suite and fixtures
tests/fixtures/      sample race and athlete configs
```
