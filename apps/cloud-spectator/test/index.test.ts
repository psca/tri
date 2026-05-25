import { describe, expect, it } from "vitest";
import worker from "../src/index";
import type { Env } from "../src/types";

const acceptedRouteEventEnvelope = {
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

  it("accepts valid bearer auth", async () => {
    const db = {
      prepare(sql: string) {
        return {
          bind() {
            return {
              sql,
              toString: () => sql,
            };
          },
        };
      },
      batch: async () => [{ success: true }, { success: true }],
    } as unknown as D1Database;

    const response = await worker.fetch(
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: JSON.stringify(acceptedRouteEventEnvelope),
      }),
      envWith(db),
    );

    expect(response.status).toBe(202);
  });

  it("accepts accepted_route_event and makes duplicate retries safe", async () => {
    const statements: string[] = [];
    let batchCalls = 0;
    const db = {
      prepare(sql: string) {
        statements.push(sql);
        return {
          bind() {
            return {
              toString: () => sql,
              first: async () => {
                return { payload_hash: "abc" };
              },
            };
          },
        };
      },
      batch: async (batchStatements: D1PreparedStatement[]) => {
        batchCalls += 1;
        statements.push(...batchStatements.map((statement) => String(statement)));
        if (batchCalls === 1) {
          return [{ success: true }, { success: true }];
        }
        throw new Error("D1_ERROR: UNIQUE constraint failed: sync_items.idempotency_key");
      },
    } as unknown as D1Database;

    const request = () =>
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: JSON.stringify(acceptedRouteEventEnvelope),
      });

    const first = await worker.fetch(request(), envWith(db));
    const duplicate = await worker.fetch(request(), envWith(db));

    expect(first.status).toBe(202);
    expect(await first.json()).toEqual({ status: "accepted" });
    expect(duplicate.status).toBe(202);
    expect(await duplicate.json()).toEqual({ status: "duplicate" });
    expect(statements.some((sql) => sql.includes("INSERT INTO sync_items"))).toBe(true);
    expect(statements.some((sql) => sql.includes("INSERT INTO accepted_route_events"))).toBe(true);
  });

  it("rejects duplicate idempotency keys with different hashes", async () => {
    const db = {
      prepare() {
        return {
          bind() {
            return {
              first: async () => ({ payload_hash: "different" }),
            };
          },
        };
      },
      batch: async () => {
        throw new Error("D1_ERROR: UNIQUE constraint failed: sync_items.idempotency_key");
      },
    } as unknown as D1Database;

    const response = await worker.fetch(
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: JSON.stringify(acceptedRouteEventEnvelope),
      }),
      envWith(db),
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ error: "idempotency_key_conflict" });
  });

  it("does not leave sync metadata when accepted_route_event projection batch fails", async () => {
    let firstCalls = 0;
    let batchCalls = 0;
    const db = {
      prepare() {
        return {
          bind() {
            return {
              first: async () => {
                firstCalls += 1;
                return null;
              },
            };
          },
        };
      },
      batch: async () => {
        batchCalls += 1;
        throw new Error("projection insert failed");
      },
    } as unknown as D1Database;

    const request = () =>
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: JSON.stringify(acceptedRouteEventEnvelope),
      });

    await expect(worker.fetch(request(), envWith(db))).rejects.toThrow("projection insert failed");
    await expect(worker.fetch(request(), envWith(db))).rejects.toThrow("projection insert failed");

    expect(batchCalls).toBe(2);
    expect(firstCalls).toBe(2);
  });

  it("rejects invalid envelopes before writing bad rows", async () => {
    let prepareCalls = 0;
    const db = {
      prepare() {
        prepareCalls += 1;
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

    const response = await worker.fetch(
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
        body: JSON.stringify({ ...acceptedRouteEventEnvelope, payload: { athlete_id: "A001" } }),
      }),
      envWith(db),
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "bad_request" });
    expect(prepareCalls).toBe(0);
  });
});
