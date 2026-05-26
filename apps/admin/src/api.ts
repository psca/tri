import type { ManualCorrectionRequest, RaceStateView, ReceiverHealthResponse, ReviewState } from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

export function getRaceState(): Promise<RaceStateView> {
  return requestJson<RaceStateView>("/api/race/state");
}

export function startRace(): Promise<RaceStateView> {
  return requestJson<RaceStateView>("/api/race/start", { method: "POST" });
}

export function closeRace(): Promise<RaceStateView> {
  return requestJson<RaceStateView>("/api/race/close", { method: "POST" });
}

export function sendSyntheticDetection(athleteId: string, checkpointId: string): Promise<RaceStateView> {
  return requestJson<RaceStateView>("/api/synthetic/detection", {
    method: "POST",
    body: JSON.stringify({
      athlete_id: athleteId,
      checkpoint_id: checkpointId,
      receiver_id: "admin",
      rssi: -55,
      repeat_count: 6,
    }),
  });
}

export function getReceiverHealth(): Promise<ReceiverHealthResponse> {
  return requestJson<ReceiverHealthResponse>("/api/receivers/health");
}

export function getReviewState(): Promise<ReviewState> {
  return requestJson<ReviewState>("/api/review/state");
}

export function submitCorrection(payload: ManualCorrectionRequest): Promise<ReviewState> {
  return requestJson<ReviewState>("/api/corrections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
