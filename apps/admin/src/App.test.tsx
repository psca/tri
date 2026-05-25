import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";

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
        warnings: [],
      }),
    })),
  );
});

test("renders Bob and next event from api", async () => {
  render(<App />);

  expect(await screen.findByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("run1_lap1_complete")).toBeInTheDocument();
});
