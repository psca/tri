# Cloud Spectator Acceptance Checklist

- [ ] Local race service continues timing with the cloud endpoint unavailable.
- [ ] Accepted route events create pending local sync outbox rows.
- [ ] Publisher uploads pending outbox rows when the ingest endpoint is available.
- [ ] Failed uploads remain retryable and do not block local timing authority behavior.
- [ ] Authenticated ingest accepts valid sync envelopes at `POST /api/ingest`.
- [ ] Duplicate upload with the same idempotency key and payload hash is accepted.
- [ ] Duplicate upload with the same idempotency key and different payload hash returns conflict.
- [ ] Accepted route event projection writes D1 sync metadata and spectator event rows atomically.
- [ ] Public events API returns accepted route events in local sequence order.
- [ ] Public state API returns the latest race snapshot or JSON 404 when absent.
- [ ] Invalid or unauthenticated ingest requests do not write D1 rows.
- [ ] No raw BLE detections are uploaded by default.

## Verification

Run the end-to-end documentation task checks from the repository root:

```bash
cd apps/local-core
uv run pytest -v
```

```bash
cd apps/admin
npm test
npm run build
```

```bash
cd apps/cloud-spectator
npm test -- --run
npm run typecheck
```
