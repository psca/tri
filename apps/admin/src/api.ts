import type { ManualCorrectionRequest, RaceStateView, ReviewState } from "./types";

async function requestState(path: string, init?: RequestInit): Promise<RaceStateView> {
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
  return requestState("/api/race/state");
}

export function startRace(): Promise<RaceStateView> {
  return requestState("/api/race/start", { method: "POST" });
}

export function closeRace(): Promise<RaceStateView> {
  return requestState("/api/race/close", { method: "POST" });
}

export function sendSyntheticDetection(athleteId: string, checkpointId: string): Promise<RaceStateView> {
  return requestState("/api/synthetic/detection", {
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

async function requestReview(path: string, init?: RequestInit): Promise<ReviewState> {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

export function getReviewState(): Promise<ReviewState> {
  return requestReview("/api/review/state");
}

export function submitCorrection(payload: ManualCorrectionRequest): Promise<ReviewState> {
  return requestReview("/api/corrections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
