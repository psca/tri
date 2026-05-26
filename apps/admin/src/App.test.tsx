import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { getReviewState, submitCorrection } from "./api";
import type { RaceStateView } from "./types";

class MockEventSource {
  static last: MockEventSource | null = null;

  readonly url: string;
  readonly close = vi.fn();
  private readonly listeners = new Map<string, (event: MessageEvent<string>) => void>();

  constructor(url: string) {
    this.url = url;
    MockEventSource.last = this;
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener);
  }

  emit(type: string, state: RaceStateView) {
    this.listeners.get(type)?.({ data: JSON.stringify(state) } as MessageEvent<string>);
  }
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const payload = path.includes("/api/review/state")
        ? {
            race_id: "duathlon-demo",
            phase: "pre_start",
            route_events: [],
            athletes: [],
            correction_log: [],
            warnings: [],
            raw_detections: [],
          }
        : {
            race_id: "duathlon-001",
            phase: "pre_start",
            athletes: [
              {
                athlete_id: "A001",
                name: "Bob",
                bib_number: "1",
                next_event_id: "run1_lap1_complete",
                status: "racing",
              },
            ],
            accepted_events: [],
            raw_detections: [],
            warnings: [],
          };
      return {
        ok: true,
        json: async () => payload,
      };
    }),
  );
  vi.stubGlobal("EventSource", MockEventSource);
  MockEventSource.last = null;
});

test("renders Bob and next event from api", async () => {
  render(<App />);

  expect(await screen.findByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("run1_lap1_complete")).toBeInTheDocument();
});

test("subscribes to event stream and applies state messages", async () => {
  render(<App />);

  expect(await screen.findByText("Bob")).toBeInTheDocument();
  expect(MockEventSource.last?.url).toBe("/api/events/stream");

  act(() => {
    MockEventSource.last?.emit("state", {
      race_id: "duathlon-001",
      phase: "live",
      athletes: [
        {
          athlete_id: "A001",
          name: "Bob",
          bib_number: "1",
          next_event_id: "run1_lap2_complete",
          status: "racing",
        },
      ],
      accepted_events: [],
      raw_detections: [
        {
          local_sequence_number: 1,
          receiver_id: "admin",
          checkpoint_id: "gate",
          beacon_uuid: "11111111-1111-1111-1111-111111111111",
          beacon_major: 1,
          beacon_minor: 2,
          rssi: -55,
          timestamp_wall: "2026-05-25T08:00:00+08:00",
        },
      ],
      warnings: [],
    });
  });

  expect(screen.getByText("live")).toBeInTheDocument();
  expect(screen.getByText("run1_lap2_complete")).toBeInTheDocument();
  expect(screen.getByText("admin · gate · -55 dBm")).toBeInTheDocument();
});

test("submitCorrection posts correction payload and returns review state", async () => {
  const reviewState = {
    race_id: "duathlon-demo",
    phase: "live",
    athletes: [],
    route_events: [],
    correction_log: [],
    warnings: [],
    raw_detections: [],
  };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(reviewState), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );

  await expect(
    submitCorrection({
      correction_type: "manual_add_pass",
      athlete_id: "A001",
      route_event_id: "run1_lap1_complete",
      corrected_time_wall: "2026-05-25T09:10:00+08:00",
      reason: "Saw athlete cross",
      created_by: "operator",
    }),
  ).resolves.toEqual(reviewState);

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/corrections",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        correction_type: "manual_add_pass",
        athlete_id: "A001",
        route_event_id: "run1_lap1_complete",
        corrected_time_wall: "2026-05-25T09:10:00+08:00",
        reason: "Saw athlete cross",
        created_by: "operator",
      }),
    }),
  );
  fetchMock.mockRestore();
});

test("getReviewState fetches review state", async () => {
  const reviewState = {
    race_id: "duathlon-demo",
    phase: "live",
    athletes: [],
    route_events: [],
    correction_log: [],
    warnings: [],
    raw_detections: [],
  };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(reviewState), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );

  await expect(getReviewState()).resolves.toEqual(reviewState);

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/review/state",
    expect.objectContaining({ headers: { "content-type": "application/json" } }),
  );
  fetchMock.mockRestore();
});

test("review mode renders athlete timeline and correction actions", async () => {
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
    const path = String(input);
    const payload = path.includes("/api/review/state")
      ? {
          race_id: "duathlon-demo",
          phase: "live",
          route_events: [{ id: "run1_lap1_complete", label: "Run 1 Lap 1", index: 1 }],
          athletes: [
            {
              athlete_id: "A001",
              name: "Bob",
              bib_number: "1",
              status: "racing",
              next_event_id: "run1_lap1_complete",
              completed_count: 0,
              total_count: 1,
              attention_level: "needs_attention",
              badges: ["missing pass"],
              timeline: [
                {
                  route_event_id: "run1_lap1_complete",
                  label: "Run 1 Lap 1",
                  status: "missing",
                  timestamp: null,
                  confidence: null,
                  source: "none",
                },
              ],
            },
          ],
          correction_log: [],
          warnings: [],
          raw_detections: [],
        }
      : {
          race_id: "duathlon-001",
          phase: "live",
          athletes: [],
          accepted_events: [],
          raw_detections: [],
          warnings: [],
        };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));

  expect(await screen.findByRole("button", { name: /Bob/ })).toBeInTheDocument();
  expect(screen.getByText("Run 1 Lap 1")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: "Add missing pass" })).toBeInTheDocument();
  expect(screen.getByLabelText("Reason")).toBeRequired();
});

test("review mode submits a manual add pass correction", async () => {
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/corrections") {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({
        correction_type: "manual_add_pass",
        athlete_id: "A001",
        route_event_id: "run1_lap1_complete",
        corrected_time_wall: "2026-05-25T09:10:00+08:00",
        reason: "Saw athlete cross",
        created_by: "operator",
      });
    }

    const reviewPayload = {
      race_id: "duathlon-demo",
      phase: "live",
      route_events: [{ id: "run1_lap1_complete", label: "Run 1 Lap 1", index: 1 }],
      athletes: [
        {
          athlete_id: "A001",
          name: "Bob",
          bib_number: "1",
          status: "racing",
          next_event_id: "run1_lap1_complete",
          completed_count: 0,
          total_count: 1,
          attention_level: "needs_attention",
          badges: [],
          timeline: [
            {
              route_event_id: "run1_lap1_complete",
              label: "Run 1 Lap 1",
              status: "missing",
              timestamp: null,
              confidence: null,
              source: "none",
            },
          ],
        },
      ],
      correction_log: [],
      warnings: [],
      raw_detections: [],
    };
    const racePayload = {
      race_id: "duathlon-001",
      phase: "live",
      athletes: [],
      accepted_events: [],
      raw_detections: [],
      warnings: [],
    };
    return new Response(JSON.stringify(path.includes("/api/race/state") ? racePayload : reviewPayload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
  fireEvent.change(await screen.findByLabelText("Corrected time"), {
    target: { value: "2026-05-25T09:10:00+08:00" },
  });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Saw athlete cross" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/corrections", expect.any(Object)));
  await waitFor(() =>
    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/review/state").length).toBeGreaterThanOrEqual(3),
  );
});
