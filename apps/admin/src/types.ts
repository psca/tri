export type AthleteView = {
  athlete_id: string;
  name: string;
  bib_number: string | null;
  next_event_id: string | null;
  status: string;
};

export type AcceptedEventView = {
  athlete_id: string;
  route_event_id: string;
  checkpoint_id: string;
  timestamp: string;
  confidence: string;
};

export type RawDetectionView = {
  local_sequence_number: number;
  receiver_id: string;
  checkpoint_id: string;
  beacon_uuid: string;
  beacon_major: number;
  beacon_minor: number;
  rssi: number;
  timestamp_wall: string;
};

export type ReceiverBeaconHealthView = {
  athlete_id: string;
  beacon_uuid: string;
  beacon_major: number;
  beacon_minor: number;
  rssi: number;
  timestamp_wall: string;
};

export type ReceiverHealthView = {
  receiver_id: string;
  checkpoint_id: string;
  status: "online" | "stale" | "silent";
  last_packet_wall: string | null;
  known_packets: number;
  unknown_packets: number;
  latest_known_beacons: ReceiverBeaconHealthView[];
};

export type ReceiverHealthResponse = {
  receivers: ReceiverHealthView[];
};

export type RaceStateView = {
  race_id: string;
  phase: string;
  athletes: AthleteView[];
  accepted_events: AcceptedEventView[];
  raw_detections: RawDetectionView[];
  warnings: string[];
};

export type ReviewTimelineEvent = {
  route_event_id: string;
  label: string;
  status: "pending" | "accepted" | "missing" | "manual" | "overridden" | "rejected";
  timestamp: string | null;
  confidence: string | null;
  source: "ble" | "manual" | "override" | "none";
  accepted_local_sequence_number?: number | null;
  original_timestamp?: string | null;
  correction_sequence_numbers?: number[];
};

export type ReviewAthlete = {
  athlete_id: string;
  name: string;
  bib_number: string | null;
  status: string;
  next_event_id: string | null;
  completed_count: number;
  total_count: number;
  attention_level: "needs_attention" | "ok";
  badges: string[];
  timeline: ReviewTimelineEvent[];
};

export type ReviewState = {
  race_id: string;
  phase: string;
  route_events: Array<{ id: string; label: string; index: number }>;
  athletes: ReviewAthlete[];
  correction_log: Record<string, unknown>[];
  warnings: string[];
  raw_detections: RawDetectionView[];
};

export type ManualCorrectionRequest = {
  correction_type: "manual_add_pass" | "manual_reject_pass" | "manual_override_time" | "mark_status";
  athlete_id: string;
  route_event_id?: string | null;
  target_local_sequence_number?: number | null;
  corrected_time_wall?: string | null;
  status?: string | null;
  reason: string;
  created_by: string;
};
