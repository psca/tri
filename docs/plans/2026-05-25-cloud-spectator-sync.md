# Cloud Spectator Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Cloudflare spectator sync so the local timing service can publish accepted race state to a read-only cloud dashboard API without becoming dependent on internet connectivity.

**Architecture:** Local SQLite remains canonical. `tri_timing_service` adds a retrying outbox publisher. `apps/cloud-spectator` is a Cloudflare Worker with D1 migrations, optional R2 backup binding, authenticated ingest, and public read APIs.

**Tech Stack:** Python 3.11+, `uv`, FastAPI/httpx, pytest, Cloudflare Workers, TypeScript, Wrangler, D1, R2, Vitest.

---

## File Structure

```text
apps/local-core/
  src/tri_timing/store.py
  src/tri_timing_service/sync.py
  src/tri_timing_service/runtime.py
  src/tri_timing_service/settings.py
  tests/test_store.py
  tests/test_sync_publisher.py
  tests/test_service_runtime.py

apps/cloud-spectator/
  package.json
  tsconfig.json
  vitest.config.ts
  wrangler.jsonc
  migrations/0001_initial.sql
  src/index.ts
  src/auth.ts
  src/ingest.ts
  src/read-model.ts
  src/types.ts
  test/index.test.ts
```

## Task 1: Extend Local Outbox Status

**Files:**
- Modify: `apps/local-core/src/tri_timing/store.py`
- Modify: `apps/local-core/tests/test_store.py`

- [ ] **Step 1: Add failing store test**

Append to `apps/local-core/tests/test_store.py`:

```python
def test_sync_outbox_rows_can_be_marked_synced(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    pending = store.pending_sync_outbox(limit=10)
    assert [row["local_sequence_number"] for row in pending] == [sequence]

    store.mark_sync_success(sequence, synced_at="2026-05-25T09:00:05+00:00")

    assert store.pending_sync_outbox(limit=10) == []
    row = store.sync_outbox()[0]
    assert row["status"] == "synced"
    assert row["synced_at"] == "2026-05-25T09:00:05+00:00"
```

- [ ] **Step 2: Run failing test**

Run from `apps/local-core`:

```bash
uv run pytest tests/test_store.py::test_sync_outbox_rows_can_be_marked_synced -v
```

Expected: fail because `pending_sync_outbox`, `mark_sync_success`, and `synced_at` do not exist.

- [ ] **Step 3: Implement outbox status helpers**

Modify `sync_outbox` migration in `apps/local-core/src/tri_timing/store.py` to add columns idempotently after the existing table creation:

```python
def _ensure_column(self, table: str, column: str, ddl: str) -> None:
    rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {str(row["name"]) for row in rows}:
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

Call from `_migrate()`:

```python
self._ensure_column("sync_outbox", "synced_at", "synced_at TEXT")
self._ensure_column("sync_outbox", "next_attempt_at", "next_attempt_at TEXT")
```

Add methods:

```python
def pending_sync_outbox(self, *, limit: int) -> list[dict[str, Any]]:
    rows = self.conn.execute(
        """
        SELECT * FROM sync_outbox
        WHERE status IN ('pending', 'failed_retryable')
        ORDER BY local_sequence_number
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]

def mark_sync_success(self, local_sequence_number: int, *, synced_at: str) -> None:
    with self.conn:
        self.conn.execute(
            """
            UPDATE sync_outbox
            SET status = 'synced', synced_at = ?, last_error = NULL
            WHERE local_sequence_number = ?
            """,
            (synced_at, local_sequence_number),
        )

def mark_sync_failure(
    self,
    local_sequence_number: int,
    *,
    error: str,
    next_attempt_at: str | None,
) -> None:
    with self.conn:
        self.conn.execute(
            """
            UPDATE sync_outbox
            SET status = 'failed_retryable',
                attempts = attempts + 1,
                last_error = ?,
                next_attempt_at = ?
            WHERE local_sequence_number = ?
            """,
            (error, next_attempt_at, local_sequence_number),
        )
```

- [ ] **Step 4: Verify test passes**

```bash
uv run pytest tests/test_store.py::test_sync_outbox_rows_can_be_marked_synced -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing/store.py apps/local-core/tests/test_store.py
git commit -m "feat: track sync outbox status"
```

## Task 2: Add Local Sync Publisher

**Files:**
- Create: `apps/local-core/src/tri_timing_service/sync.py`
- Modify: `apps/local-core/src/tri_timing_service/settings.py`
- Create: `apps/local-core/tests/test_sync_publisher.py`

- [ ] **Step 1: Add failing publisher tests**

Create `apps/local-core/tests/test_sync_publisher.py`:

```python
import httpx
import pytest

from tri_timing.store import EventStore
from tri_timing_service.sync import SyncPublisher


@pytest.mark.asyncio
async def test_sync_publisher_marks_success(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.path == "/api/ingest"
        return httpx.Response(202, json={"status": "accepted"})

    publisher = SyncPublisher(
        store=store,
        endpoint="https://example.test/api/ingest",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    result = await publisher.publish_once()

    assert result.uploaded == 1
    assert store.pending_sync_outbox(limit=10) == []


@pytest.mark.asyncio
async def test_sync_publisher_marks_retryable_failure(tmp_path) -> None:
    store = EventStore(tmp_path / "race.sqlite")
    sequence = store.append_accepted_route_event(
        race_id="duathlon-001",
        athlete_id="A001",
        route_event_id="run1_lap1_complete",
        checkpoint_id="gate",
        pass_candidate_id="candidate-1",
        event_time_wall="2026-05-25T09:00:00+00:00",
        confidence="high",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    publisher = SyncPublisher(
        store=store,
        endpoint="https://example.test/api/ingest",
        token="secret",
        transport=httpx.MockTransport(handler),
    )

    result = await publisher.publish_once()

    assert result.uploaded == 0
    row = store.sync_outbox()[0]
    assert row["local_sequence_number"] == sequence
    assert row["status"] == "failed_retryable"
    assert row["attempts"] == 1
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/test_sync_publisher.py -v
```

Expected: fail because `tri_timing_service.sync` does not exist.

- [ ] **Step 3: Add publisher implementation**

Create `apps/local-core/src/tri_timing_service/sync.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from tri_timing.store import EventStore


@dataclass(frozen=True)
class PublishResult:
    uploaded: int
    failed: int


class SyncPublisher:
    def __init__(
        self,
        *,
        store: EventStore,
        endpoint: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._store = store
        self._endpoint = endpoint
        self._token = token
        self._transport = transport

    async def publish_once(self, *, limit: int = 10) -> PublishResult:
        rows = self._store.pending_sync_outbox(limit=limit)
        uploaded = 0
        failed = 0
        async with httpx.AsyncClient(transport=self._transport, timeout=5.0) as client:
            for row in rows:
                envelope = self._envelope(row)
                try:
                    response = await client.post(
                        self._endpoint,
                        json=envelope,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                except httpx.HTTPError as exc:
                    self._store.mark_sync_failure(
                        int(row["local_sequence_number"]),
                        error=str(exc),
                        next_attempt_at=None,
                    )
                    failed += 1
                    continue

                if response.status_code in {200, 201, 202}:
                    self._store.mark_sync_success(
                        int(row["local_sequence_number"]),
                        synced_at=datetime.now(tz=UTC).isoformat(),
                    )
                    uploaded += 1
                else:
                    self._store.mark_sync_failure(
                        int(row["local_sequence_number"]),
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
                        next_attempt_at=None,
                    )
                    failed += 1

        return PublishResult(uploaded=uploaded, failed=failed)

    def _envelope(self, row: dict[str, object]) -> dict[str, object]:
        payload = json.loads(str(row["payload_json"]))
        return {
            "idempotency_key": row["idempotency_key"],
            "payload_hash": row["payload_hash"],
            "race_id": payload["race_id"],
            "local_sequence_number": row["local_sequence_number"],
            "type": payload["type"],
            "created_at": datetime.now(tz=UTC).isoformat(),
            "payload": payload,
        }
```

- [ ] **Step 4: Verify publisher tests pass**

```bash
uv run pytest tests/test_sync_publisher.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing_service/sync.py apps/local-core/tests/test_sync_publisher.py
git commit -m "feat: add local sync publisher"
```

## Task 3: Scaffold Cloudflare Worker

**Files:**
- Create: `apps/cloud-spectator/package.json`
- Create: `apps/cloud-spectator/tsconfig.json`
- Create: `apps/cloud-spectator/vitest.config.ts`
- Create: `apps/cloud-spectator/wrangler.jsonc`
- Create: `apps/cloud-spectator/migrations/0001_initial.sql`
- Create: `apps/cloud-spectator/src/types.ts`
- Create: `apps/cloud-spectator/src/index.ts`

- [ ] **Step 1: Create package config**

Create `apps/cloud-spectator/package.json`:

```json
{
  "name": "@tri-timing/cloud-spectator",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "test": "vitest",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@cloudflare/vitest-pool-workers": "latest",
    "@cloudflare/workers-types": "latest",
    "typescript": "latest",
    "vitest": "latest",
    "wrangler": "latest"
  }
}
```

Create `apps/cloud-spectator/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "types": ["@cloudflare/workers-types"],
    "noEmit": true
  },
  "include": ["src", "test"]
}
```

Create `apps/cloud-spectator/vitest.config.ts`:

```ts
import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.jsonc" },
      },
    },
  },
});
```

- [ ] **Step 2: Create Wrangler config**

Create `apps/cloud-spectator/wrangler.jsonc`:

```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "tri-timing-cloud-spectator",
  "main": "src/index.ts",
  "compatibility_date": "2026-05-25",
  "compatibility_flags": ["nodejs_compat"],
  "observability": {
    "enabled": true,
    "head_sampling_rate": 1
  },
  "d1_databases": [
    {
      "binding": "DB",
      "database_name": "tri-timing-spectator",
      "database_id": "local-placeholder"
    }
  ],
  "r2_buckets": [
    {
      "binding": "BACKUP_BUCKET",
      "bucket_name": "tri-timing-backups"
    }
  ]
}
```

- [ ] **Step 3: Create D1 migration**

Create `apps/cloud-spectator/migrations/0001_initial.sql`:

```sql
CREATE TABLE IF NOT EXISTS sync_items (
  idempotency_key TEXT PRIMARY KEY,
  race_id TEXT NOT NULL,
  local_sequence_number INTEGER NOT NULL,
  type TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS races (
  race_id TEXT PRIMARY KEY,
  name TEXT,
  phase TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accepted_route_events (
  race_id TEXT NOT NULL,
  local_sequence_number INTEGER NOT NULL,
  athlete_id TEXT NOT NULL,
  route_event_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  event_time_wall TEXT NOT NULL,
  confidence TEXT NOT NULL,
  PRIMARY KEY (race_id, local_sequence_number)
);

CREATE TABLE IF NOT EXISTS receiver_health (
  race_id TEXT NOT NULL,
  receiver_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  status TEXT NOT NULL,
  last_packet_at TEXT,
  packet_rate REAL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (race_id, receiver_id)
);
```

- [ ] **Step 4: Add minimal Worker**

Create `apps/cloud-spectator/src/types.ts`:

```ts
export interface Env {
  DB: D1Database;
  BACKUP_BUCKET: R2Bucket;
  INGEST_TOKEN: string;
}
```

Create `apps/cloud-spectator/src/index.ts`:

```ts
import type { Env } from "./types";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return Response.json({ status: "ok" });
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  },
};
```

- [ ] **Step 5: Install and typecheck**

Run from `apps/cloud-spectator`:

```bash
npm install
npm run typecheck
```

Expected: typecheck passes.

- [ ] **Step 6: Commit**

```bash
git add apps/cloud-spectator
git commit -m "feat: scaffold cloud spectator worker"
```

## Task 4: Add Authenticated Ingest

**Files:**
- Create: `apps/cloud-spectator/src/auth.ts`
- Create: `apps/cloud-spectator/src/ingest.ts`
- Modify: `apps/cloud-spectator/src/index.ts`
- Create: `apps/cloud-spectator/test/index.test.ts`

- [ ] **Step 1: Add failing Worker tests**

Create `apps/cloud-spectator/test/index.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import type { Env } from "../src/types";

function envWith(db: D1Database): Env {
  return {
    DB: db,
    BACKUP_BUCKET: {} as R2Bucket,
    INGEST_TOKEN: "secret",
  };
}

describe("ingest", () => {
  it("rejects missing auth", async () => {
    const response = await worker.fetch(
      new Request("https://example.test/api/ingest", { method: "POST" }),
      envWith({} as D1Database),
    );

    expect(response.status).toBe(401);
  });
});
```

- [ ] **Step 2: Run failing test**

```bash
npm test -- --run
```

Expected: fail until the test environment is wired and `/api/ingest` exists.

- [ ] **Step 3: Implement auth helper**

Create `apps/cloud-spectator/src/auth.ts`:

```ts
export async function hasValidBearerToken(request: Request, expected: string): Promise<boolean> {
  const header = request.headers.get("authorization");
  const actual = header?.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";
  const encoder = new TextEncoder();
  const actualBytes = encoder.encode(actual);
  const expectedBytes = encoder.encode(expected);
  const lengthsMatch = actualBytes.byteLength === expectedBytes.byteLength;
  return lengthsMatch
    ? crypto.subtle.timingSafeEqual(actualBytes, expectedBytes)
    : !crypto.subtle.timingSafeEqual(actualBytes, actualBytes);
}
```

- [ ] **Step 4: Implement ingest route skeleton**

Create `apps/cloud-spectator/src/ingest.ts`:

```ts
import { hasValidBearerToken } from "./auth";
import type { Env } from "./types";

export async function handleIngest(request: Request, env: Env): Promise<Response> {
  if (!(await hasValidBearerToken(request, env.INGEST_TOKEN))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  return Response.json({ status: "accepted" }, { status: 202 });
}
```

Modify `apps/cloud-spectator/src/index.ts`:

```ts
import { handleIngest } from "./ingest";
import type { Env } from "./types";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return Response.json({ status: "ok" });
    }
    if (url.pathname === "/api/ingest" && request.method === "POST") {
      return handleIngest(request, env);
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  },
};
```

- [ ] **Step 5: Verify tests/typecheck**

```bash
npm test -- --run
npm run typecheck
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/cloud-spectator/src apps/cloud-spectator/test
git commit -m "feat: add cloud ingest auth"
```

## Task 5: Project Accepted Events Into D1

**Files:**
- Create: `apps/cloud-spectator/src/read-model.ts`
- Modify: `apps/cloud-spectator/src/ingest.ts`
- Modify: `apps/cloud-spectator/test/index.test.ts`

- [ ] **Step 1: Add ingest projection test**

Append to `apps/cloud-spectator/test/index.test.ts`:

```ts
it("accepts accepted_route_event and makes duplicate retries safe", async () => {
  const statements: string[] = [];
  const db = {
    prepare(sql: string) {
      statements.push(sql);
      return {
        bind() {
          return {
            first: async () => null,
            run: async () => ({ success: true }),
          };
        },
      };
    },
  } as unknown as D1Database;

  const body = {
    idempotency_key: "duathlon-001:42",
    payload_hash: "abc",
    race_id: "duathlon-001",
    local_sequence_number: 42,
    type: "accepted_route_event",
    created_at: "2026-05-25T09:00:00Z",
    payload: {
      type: "accepted_route_event",
      race_id: "duathlon-001",
      local_sequence_number: 42,
      athlete_id: "A001",
      route_event_id: "run1_lap1_complete",
      checkpoint_id: "gate",
      event_time_wall: "2026-05-25T09:00:00Z",
      confidence: "high",
    },
  };

  const response = await worker.fetch(
    new Request("https://example.test/api/ingest", {
      method: "POST",
      headers: { authorization: "Bearer secret" },
      body: JSON.stringify(body),
    }),
    envWith(db),
  );

  expect(response.status).toBe(202);
  expect(statements.some((sql) => sql.includes("INSERT INTO sync_items"))).toBe(true);
  expect(statements.some((sql) => sql.includes("INSERT INTO accepted_route_events"))).toBe(true);
});
```

- [ ] **Step 2: Run failing test**

```bash
npm test -- --run
```

Expected: fail because the ingest handler does not write D1 rows.

- [ ] **Step 3: Add read-model projection**

Create `apps/cloud-spectator/src/read-model.ts`:

```ts
export interface SyncEnvelope {
  idempotency_key: string;
  payload_hash: string;
  race_id: string;
  local_sequence_number: number;
  type: "accepted_route_event" | "race_state_snapshot" | "receiver_health_snapshot";
  created_at: string;
  payload: Record<string, unknown>;
}

export async function projectEnvelope(db: D1Database, envelope: SyncEnvelope): Promise<"accepted" | "duplicate"> {
  const existing = await db
    .prepare("SELECT payload_hash FROM sync_items WHERE idempotency_key = ?")
    .bind(envelope.idempotency_key)
    .first<{ payload_hash: string }>();

  if (existing) {
    if (existing.payload_hash !== envelope.payload_hash) {
      throw new Error("idempotency_key_conflict");
    }
    return "duplicate";
  }

  await db
    .prepare(
      "INSERT INTO sync_items (idempotency_key, race_id, local_sequence_number, type, payload_hash, received_at) VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(
      envelope.idempotency_key,
      envelope.race_id,
      envelope.local_sequence_number,
      envelope.type,
      envelope.payload_hash,
      new Date().toISOString(),
    )
    .run();

  if (envelope.type === "accepted_route_event") {
    const payload = envelope.payload;
    await db
      .prepare(
        "INSERT INTO accepted_route_events (race_id, local_sequence_number, athlete_id, route_event_id, checkpoint_id, event_time_wall, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
      )
      .bind(
        envelope.race_id,
        envelope.local_sequence_number,
        String(payload.athlete_id),
        String(payload.route_event_id),
        String(payload.checkpoint_id),
        String(payload.event_time_wall),
        String(payload.confidence),
      )
      .run();
  }

  return "accepted";
}
```

Modify `apps/cloud-spectator/src/ingest.ts`:

```ts
import { hasValidBearerToken } from "./auth";
import { projectEnvelope, type SyncEnvelope } from "./read-model";
import type { Env } from "./types";

export async function handleIngest(request: Request, env: Env): Promise<Response> {
  if (!(await hasValidBearerToken(request, env.INGEST_TOKEN))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  const envelope = (await request.json()) as SyncEnvelope;
  try {
    const status = await projectEnvelope(env.DB, envelope);
    return Response.json({ status }, { status: 202 });
  } catch (error) {
    if (error instanceof Error && error.message === "idempotency_key_conflict") {
      return Response.json({ error: "idempotency_key_conflict" }, { status: 409 });
    }
    return Response.json({ error: "bad_request" }, { status: 400 });
  }
}
```

- [ ] **Step 4: Verify tests/typecheck**

```bash
npm test -- --run
npm run typecheck
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/cloud-spectator/src apps/cloud-spectator/test
git commit -m "feat: project cloud sync events"
```

## Task 6: Add Public Spectator APIs

**Files:**
- Modify: `apps/cloud-spectator/src/read-model.ts`
- Modify: `apps/cloud-spectator/src/index.ts`
- Modify: `apps/cloud-spectator/test/index.test.ts`

- [ ] **Step 1: Add public API tests**

Append to `apps/cloud-spectator/test/index.test.ts`:

```ts
it("returns accepted events for a race", async () => {
  const db = {
    prepare(sql: string) {
      return {
        bind() {
          return {
            all: async () => ({
              results: [
                {
                  race_id: "duathlon-001",
                  local_sequence_number: 42,
                  athlete_id: "A001",
                  route_event_id: "run1_lap1_complete",
                  checkpoint_id: "gate",
                  event_time_wall: "2026-05-25T09:00:00Z",
                  confidence: "high",
                },
              ],
            }),
            first: async () => null,
          };
        },
      };
    },
  } as unknown as D1Database;

  const response = await worker.fetch(
    new Request("https://example.test/api/races/duathlon-001/events"),
    envWith(db),
  );

  expect(response.status).toBe(200);
  const body = await response.json() as { events: unknown[] };
  expect(body.events).toHaveLength(1);
});
```

- [ ] **Step 2: Run failing test**

```bash
npm test -- --run
```

Expected: fail because public endpoints do not exist.

- [ ] **Step 3: Add read helpers**

Append to `apps/cloud-spectator/src/read-model.ts`:

```ts
export async function listRaceEvents(db: D1Database, raceId: string): Promise<unknown[]> {
  const result = await db
    .prepare(
      "SELECT * FROM accepted_route_events WHERE race_id = ? ORDER BY local_sequence_number",
    )
    .bind(raceId)
    .all();
  return result.results ?? [];
}

export async function getRaceState(db: D1Database, raceId: string): Promise<unknown | null> {
  const row = await db
    .prepare("SELECT snapshot_json, updated_at FROM races WHERE race_id = ?")
    .bind(raceId)
    .first<{ snapshot_json: string; updated_at: string }>();
  if (!row) return null;
  return { updated_at: row.updated_at, state: JSON.parse(row.snapshot_json) };
}
```

Modify `apps/cloud-spectator/src/index.ts`:

```ts
import { handleIngest } from "./ingest";
import { getRaceState, listRaceEvents } from "./read-model";
import type { Env } from "./types";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return Response.json({ status: "ok" });
    }
    if (url.pathname === "/api/ingest" && request.method === "POST") {
      return handleIngest(request, env);
    }

    const eventsMatch = url.pathname.match(/^\/api\/races\/([^/]+)\/events$/);
    if (eventsMatch && request.method === "GET") {
      return Response.json({ events: await listRaceEvents(env.DB, eventsMatch[1]) });
    }

    const stateMatch = url.pathname.match(/^\/api\/races\/([^/]+)\/state$/);
    if (stateMatch && request.method === "GET") {
      const state = await getRaceState(env.DB, stateMatch[1]);
      return state ? Response.json(state) : Response.json({ error: "not_found" }, { status: 404 });
    }

    return Response.json({ error: "not_found" }, { status: 404 });
  },
};
```

- [ ] **Step 4: Verify tests/typecheck**

```bash
npm test -- --run
npm run typecheck
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/cloud-spectator/src apps/cloud-spectator/test
git commit -m "feat: add spectator read APIs"
```

## Task 7: Wire Local Runtime To Publisher

**Files:**
- Modify: `apps/local-core/src/tri_timing_service/settings.py`
- Modify: `apps/local-core/src/tri_timing_service/runtime.py`
- Modify: `apps/local-core/tests/test_service_runtime.py`

- [ ] **Step 1: Add settings test**

Append to `apps/local-core/tests/test_service_runtime.py`:

```python
def test_service_settings_can_disable_cloud_sync() -> None:
    settings = ServiceSettings.for_tests()

    assert settings.cloud_sync_endpoint is None
    assert settings.cloud_sync_token is None
```

- [ ] **Step 2: Add settings fields**

Modify `ServiceSettings`:

```python
@dataclass(frozen=True)
class ServiceSettings:
    race_config_path: Path
    athletes_path: Path
    database_path: Path
    cloud_sync_endpoint: str | None = None
    cloud_sync_token: str | None = None
```

- [ ] **Step 3: Add runtime publisher method**

Append to `RaceRuntime` in `apps/local-core/src/tri_timing_service/runtime.py`:

```python
async def publish_cloud_sync_once(self) -> int:
    if not self._settings.cloud_sync_endpoint or not self._settings.cloud_sync_token:
        return 0
    publisher = SyncPublisher(
        store=self._store,
        endpoint=self._settings.cloud_sync_endpoint,
        token=self._settings.cloud_sync_token,
    )
    result = await publisher.publish_once()
    return result.uploaded
```

Add import:

```python
from tri_timing_service.sync import SyncPublisher
```

- [ ] **Step 4: Verify local tests**

```bash
uv run pytest -v
```

Expected: all local-core tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/local-core/src/tri_timing_service apps/local-core/tests
git commit -m "feat: wire runtime cloud sync"
```

## Task 8: Documentation And End-To-End Check

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Create: `docs/acceptance/cloud-spectator.md`

- [ ] **Step 1: Add acceptance checklist**

Create `docs/acceptance/cloud-spectator.md`:

```markdown
# Cloud Spectator Acceptance Checklist

- [ ] Local race service continues timing with cloud endpoint unavailable.
- [ ] Accepted route events create pending outbox rows.
- [ ] Publisher uploads pending rows when endpoint is available.
- [ ] Duplicate upload with same idempotency key and hash is accepted.
- [ ] Duplicate upload with different hash returns conflict.
- [ ] Public events API returns accepted route events in sequence order.
- [ ] Public state API returns latest race snapshot or 404 when absent.
- [ ] No raw BLE detections are uploaded by default.
```

- [ ] **Step 2: Update README layout and commands**

Add `apps/cloud-spectator/` to the repository layout and command section:

```markdown
Cloud spectator commands run from `apps/cloud-spectator`:

```bash
cd apps/cloud-spectator
npm install
npm test -- --run
npm run typecheck
npm run dev
```
```

- [ ] **Step 3: Update AGENTS architecture notes**

Add:

```markdown
- `apps/cloud-spectator/` contains the Cloudflare Worker, D1 migrations, and spectator API tests.
- Cloud sync must be idempotent. Local SQLite remains canonical; D1 is a derived read model.
```

- [ ] **Step 4: Run full verification**

Run:

```bash
cd apps/local-core
uv run pytest -v
```

Run:

```bash
cd apps/admin
npm test
npm run build
```

Run:

```bash
cd apps/cloud-spectator
npm test -- --run
npm run typecheck
```

Expected: all tests and builds pass.

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md docs/acceptance/cloud-spectator.md
git commit -m "docs: document cloud spectator sync"
```
