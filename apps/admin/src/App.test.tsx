import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
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
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
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
      }),
    })),
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
