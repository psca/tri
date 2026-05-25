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

  it("accepts valid bearer auth", async () => {
    const response = await worker.fetch(
      new Request("https://example.test/api/ingest", {
        method: "POST",
        headers: { authorization: "Bearer secret" },
      }),
      envWith({} as D1Database),
    );

    expect(response.status).toBe(202);
  });
});
