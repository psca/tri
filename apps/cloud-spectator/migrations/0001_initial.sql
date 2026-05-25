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
