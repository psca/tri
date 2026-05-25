# Local Core Acceptance Checklist

This checklist proves the local Python timing core is ready for admin UI planning.

## Required Commands

```bash
uv run pytest -v
uv run tri-timing synthetic-replay \
  --race tests/fixtures/race.yaml \
  --athletes tests/fixtures/athletes.csv \
  --output /tmp/tri-timing-result.json
cat /tmp/tri-timing-result.json
```

## Expected Result

- Test suite passes.
- Synthetic replay prints `accepted 1 route event`.
- Output JSON contains `run1_lap1_complete` for `A001`.

## Scope Confirmed

- Config loading works.
- Route compiler expands laps and transitions.
- SQLite canonical store assigns durable local sequence numbers.
- Pass detector uses RSSI hysteresis and peak time.
- Race engine blocks start-grace detections.
- Race engine advances only expected route events.
- CLI can run a synthetic replay.
