import { hasValidBearerToken } from "./auth";
import {
  BadSyncEnvelopeError,
  IdempotencyKeyConflictError,
  parseSyncEnvelope,
  projectEnvelope,
} from "./read-model";
import type { Env } from "./types";

export async function handleIngest(request: Request, env: Env): Promise<Response> {
  if (!(await hasValidBearerToken(request, env.INGEST_TOKEN))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  try {
    const envelope = parseSyncEnvelope(await request.json());
    const status = await projectEnvelope(env.DB, envelope);
    return Response.json({ status }, { status: 202 });
  } catch (error) {
    if (error instanceof IdempotencyKeyConflictError) {
      return Response.json({ error: "idempotency_key_conflict" }, { status: 409 });
    }
    if (error instanceof BadSyncEnvelopeError || error instanceof SyntaxError) {
      return Response.json({ error: "bad_request" }, { status: 400 });
    }
    throw error;
  }
}
