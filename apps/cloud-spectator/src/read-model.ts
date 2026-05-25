export interface AcceptedRouteEventPayload {
  type: "accepted_route_event";
  race_id: string;
  local_sequence_number: number;
  athlete_id: string;
  route_event_id: string;
  checkpoint_id: string;
  event_time_wall: string;
  confidence: string;
}

export type RaceEvent = Omit<AcceptedRouteEventPayload, "type">;

export interface RaceState {
  updated_at: string;
  state: unknown;
}

export interface SyncEnvelope {
  idempotency_key: string;
  payload_hash: string;
  race_id: string;
  local_sequence_number: number;
  type: "accepted_route_event" | "race_state_snapshot" | "receiver_health_snapshot";
  created_at: string;
  payload: AcceptedRouteEventPayload | Record<string, unknown>;
}

export class BadSyncEnvelopeError extends Error {
  constructor() {
    super("bad_sync_envelope");
  }
}

export class IdempotencyKeyConflictError extends Error {
  constructor() {
    super("idempotency_key_conflict");
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}

function isSyncType(value: unknown): value is SyncEnvelope["type"] {
  return (
    value === "accepted_route_event" ||
    value === "race_state_snapshot" ||
    value === "receiver_health_snapshot"
  );
}

function validateAcceptedRouteEventPayload(
  envelope: SyncEnvelope,
): asserts envelope is SyncEnvelope & { payload: AcceptedRouteEventPayload } {
  const payload = envelope.payload;
  if (
    !isRecord(payload) ||
    payload.type !== "accepted_route_event" ||
    payload.race_id !== envelope.race_id ||
    payload.local_sequence_number !== envelope.local_sequence_number ||
    !isNonEmptyString(payload.athlete_id) ||
    !isNonEmptyString(payload.route_event_id) ||
    !isNonEmptyString(payload.checkpoint_id) ||
    !isNonEmptyString(payload.event_time_wall) ||
    !isNonEmptyString(payload.confidence)
  ) {
    throw new BadSyncEnvelopeError();
  }
}

export function parseSyncEnvelope(value: unknown): SyncEnvelope {
  if (!isRecord(value)) {
    throw new BadSyncEnvelopeError();
  }

  if (
    !isNonEmptyString(value.idempotency_key) ||
    !isNonEmptyString(value.payload_hash) ||
    !isNonEmptyString(value.race_id) ||
    !isInteger(value.local_sequence_number) ||
    !isSyncType(value.type) ||
    !isNonEmptyString(value.created_at) ||
    !isRecord(value.payload)
  ) {
    throw new BadSyncEnvelopeError();
  }

  const envelope: SyncEnvelope = {
    idempotency_key: value.idempotency_key,
    payload_hash: value.payload_hash,
    race_id: value.race_id,
    local_sequence_number: value.local_sequence_number,
    type: value.type,
    created_at: value.created_at,
    payload: value.payload,
  };

  if (envelope.type === "accepted_route_event") {
    validateAcceptedRouteEventPayload(envelope);
  }

  return envelope;
}

async function resolveFailedInsert(
  db: D1Database,
  envelope: SyncEnvelope,
  cause: unknown,
): Promise<"duplicate"> {
  const existing = await db
    .prepare("SELECT payload_hash FROM sync_items WHERE idempotency_key = ?")
    .bind(envelope.idempotency_key)
    .first<{ payload_hash: string }>();

  if (!existing) {
    throw cause;
  }

  if (existing.payload_hash !== envelope.payload_hash) {
    throw new IdempotencyKeyConflictError();
  }

  return "duplicate";
}

export async function projectEnvelope(
  db: D1Database,
  envelope: SyncEnvelope,
): Promise<"accepted" | "duplicate"> {
  if (envelope.type === "accepted_route_event") {
    validateAcceptedRouteEventPayload(envelope);
  }

  const syncItemStatement = db
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
    );

  if (envelope.type === "accepted_route_event") {
    const payload = envelope.payload;
    const projectionStatement = db
      .prepare(
        "INSERT INTO accepted_route_events (race_id, local_sequence_number, athlete_id, route_event_id, checkpoint_id, event_time_wall, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
      )
      .bind(
        envelope.race_id,
        envelope.local_sequence_number,
        payload.athlete_id,
        payload.route_event_id,
        payload.checkpoint_id,
        payload.event_time_wall,
        payload.confidence,
      );

    try {
      await db.batch([syncItemStatement, projectionStatement]);
    } catch (error) {
      return resolveFailedInsert(db, envelope, error);
    }

    return "accepted";
  }

  try {
    await syncItemStatement.run();
  } catch (error) {
    return resolveFailedInsert(db, envelope, error);
  }

  return "accepted";
}

export async function listRaceEvents(db: D1Database, raceId: string): Promise<RaceEvent[]> {
  const result = await db
    .prepare(
      "SELECT race_id, local_sequence_number, athlete_id, route_event_id, checkpoint_id, event_time_wall, confidence FROM accepted_route_events WHERE race_id = ? ORDER BY local_sequence_number",
    )
    .bind(raceId)
    .all<RaceEvent>();

  return result.results ?? [];
}

export async function getRaceState(db: D1Database, raceId: string): Promise<RaceState | null> {
  const row = await db
    .prepare("SELECT updated_at, snapshot_json FROM races WHERE race_id = ?")
    .bind(raceId)
    .first<{ updated_at: string; snapshot_json: string }>();

  if (!row) {
    return null;
  }

  return { updated_at: row.updated_at, state: JSON.parse(row.snapshot_json) };
}
