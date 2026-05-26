import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { getReviewState, submitCorrection } from "./api";
import type { RaceStateView, ReviewState } from "./types";

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

  emit(type: string, state: RaceStateView | ReviewState) {
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

test("renders receiver health panel", async () => {
  vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/api/receivers/health")) {
      return new Response(
        JSON.stringify({
          receivers: [
            {
              receiver_id: "laptop-dongle-1",
              checkpoint_id: "gate",
              status: "online",
              last_packet_wall: "2026-05-26T09:00:00+08:00",
              known_packets: 3,
              unknown_packets: 1,
              latest_known_beacons: [
                {
                  athlete_id: "A001",
                  beacon_uuid: "11111111-1111-1111-1111-111111111111",
                  beacon_major: 1,
                  beacon_minor: 1,
                  rssi: -55,
                  timestamp_wall: "2026-05-26T09:00:00+08:00",
                },
              ],
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.includes("/api/review/state")) {
      return new Response(
        JSON.stringify({
          race_id: "duathlon-demo",
          phase: "live",
          route_events: [],
          athletes: [],
          correction_log: [],
          warnings: [],
          raw_detections: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    return new Response(
      JSON.stringify({
        race_id: "duathlon-demo",
        phase: "live",
        athletes: [],
        accepted_events: [],
        raw_detections: [],
        warnings: [],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });

  render(<App />);

  expect(await screen.findByText("Receiver Health")).toBeInTheDocument();
  expect(screen.getByText("laptop-dongle-1")).toBeInTheDocument();
  expect(screen.getByText("online")).toBeInTheDocument();
  expect(screen.getByText("A001 · -55 dBm")).toBeInTheDocument();
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
  expect(await screen.findByText("Confirm correction")).toBeInTheDocument();
  expect(screen.getByText("Action: Add missing pass")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm submit" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/corrections", expect.any(Object)));
  await waitFor(() =>
    expect(fetchMock.mock.calls.filter(([path]) => path === "/api/review/state").length).toBeGreaterThanOrEqual(3),
  );
});

test("review mode requires corrected time before confirmation", async () => {
  mockReviewFetch(reviewStateWithTimeline([
    {
      route_event_id: "run1_lap1_complete",
      label: "Run 1 Lap 1",
      status: "missing",
      timestamp: null,
      confidence: null,
      source: "none",
    },
  ]));

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
  fireEvent.change(await screen.findByLabelText("Reason"), { target: { value: "Saw athlete cross" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Corrected time is required");
  expect(screen.queryByText("Confirm correction")).not.toBeInTheDocument();
});

test("mark status confirms and sends manual_finished for finished status", async () => {
  const fetchMock = mockReviewFetch(reviewStateWithTimeline([
    {
      route_event_id: "finish",
      label: "Finish",
      status: "pending",
      timestamp: null,
      confidence: null,
      source: "none",
    },
  ]));

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
  fireEvent.click(await screen.findByRole("radio", { name: "Mark status" }));
  fireEvent.change(screen.getByLabelText("Status"), { target: { value: "finished" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Finished manually" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm submit" }));

  await waitFor(() =>
    expect(JSON.parse(String(fetchMock.mock.calls.find(([path]) => path === "/api/corrections")?.[1]?.body))).toEqual(
      expect.objectContaining({
        correction_type: "mark_status",
        athlete_id: "A001",
        route_event_id: null,
        status: "manual_finished",
      }),
    ),
  );
});

test("manual reject uses correction sequence fallback and disables without target", async () => {
  mockReviewFetch(reviewStateWithTimeline([
    {
      route_event_id: "run1_lap1_complete",
      label: "Run 1 Lap 1",
      status: "manual",
      timestamp: "2026-05-25T09:10:00+08:00",
      confidence: "manual",
      source: "manual",
      correction_sequence_numbers: [42],
    },
    {
      route_event_id: "run1_lap2_complete",
      label: "Run 1 Lap 2",
      status: "missing",
      timestamp: null,
      confidence: null,
      source: "none",
    },
  ]));

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
  fireEvent.click(await screen.findByRole("radio", { name: "Reject pass" }));
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Bad manual pass" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm submit" }));

  await waitFor(() =>
    expect(screen.queryByText("Confirm correction")).not.toBeInTheDocument(),
  );
  const correctionCall = vi.mocked(fetch).mock.calls.find(([path]) => path === "/api/corrections");
  expect(JSON.parse(String(correctionCall?.[1]?.body))).toEqual(expect.objectContaining({ target_local_sequence_number: 42 }));

  fireEvent.click(screen.getByRole("button", { name: /Run 1 Lap 2/ }));
  expect(screen.getByRole("button", { name: "Submit correction" })).toBeDisabled();
});

test("review mode renders timeline metadata, raw detections, correction log, and review_state SSE", async () => {
  mockReviewFetch(reviewStateWithTimeline([]));

  render(<App />);
  fireEvent.click(await screen.findByRole("tab", { name: "Review" }));
  expect(await screen.findByRole("button", { name: /Bob/ })).toBeInTheDocument();

  act(() => {
    MockEventSource.last?.emit(
      "review_state",
      reviewStateWithTimeline([
        {
          route_event_id: "run1_lap1_complete",
          label: "Run 1 Lap 1",
          status: "accepted",
          timestamp: "2026-05-25T09:10:00+08:00",
          confidence: "high",
          source: "ble",
          accepted_local_sequence_number: 7,
        },
      ]),
    );
  });

  expect(await screen.findByText("confidence: high")).toBeInTheDocument();
  expect(screen.getByText("source: ble")).toBeInTheDocument();
  expect(screen.getByText("#7 · admin · gate · -55 dBm · 2026-05-25T09:09:55+08:00")).toBeInTheDocument();
  expect(screen.getByText(/manual_add_pass/)).toBeInTheDocument();
});

function mockReviewFetch(reviewPayload: ReviewState) {
  const racePayload = {
    race_id: "duathlon-001",
    phase: "live",
    athletes: [],
    accepted_events: [],
    raw_detections: [],
    warnings: [],
  };
  const fetchMock = vi.mocked(fetch);
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/corrections") {
      return new Response(JSON.stringify(reviewPayload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify(path.includes("/api/race/state") ? racePayload : reviewPayload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  return fetchMock;
}

function reviewStateWithTimeline(timeline: ReviewState["athletes"][number]["timeline"]): ReviewState {
  return {
    race_id: "duathlon-demo",
    phase: "live",
    route_events: [
      { id: "run1_lap1_complete", label: "Run 1 Lap 1", index: 1 },
      { id: "run1_lap2_complete", label: "Run 1 Lap 2", index: 2 },
    ],
    athletes: [
      {
        athlete_id: "A001",
        name: "Bob",
        bib_number: "1",
        status: "racing",
        next_event_id: "run1_lap1_complete",
        completed_count: 0,
        total_count: 2,
        attention_level: "needs_attention",
        badges: ["missing pass"],
        timeline,
      },
    ],
    correction_log: [
      {
        correction_type: "manual_add_pass",
        athlete_id: "A001",
        route_event_id: "run1_lap1_complete",
        created_by: "operator",
        reason: "Saw athlete cross",
      },
    ],
    warnings: [],
    raw_detections: [
      {
        local_sequence_number: 7,
        receiver_id: "admin",
        checkpoint_id: "gate",
        beacon_uuid: "11111111-1111-1111-1111-111111111111",
        beacon_major: 1,
        beacon_minor: 2,
        rssi: -55,
        timestamp_wall: "2026-05-25T09:09:55+08:00",
      },
    ],
  };
}
