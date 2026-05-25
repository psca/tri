import { handleIngest } from "./ingest";
import { getRaceState, listRaceEvents } from "./read-model";
import type { Env } from "./types";

function matchRacePath(pathname: string, suffix: "events" | "state"): string | null {
  const match = pathname.match(new RegExp(`^/api/races/([^/]+)/${suffix}$`));
  if (!match) {
    return null;
  }

  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return Response.json({ status: "ok" });
    }
    if (url.pathname === "/api/ingest" && request.method === "POST") {
      return handleIngest(request, env);
    }
    if (request.method === "GET") {
      const eventsRaceId = matchRacePath(url.pathname, "events");
      if (eventsRaceId) {
        return Response.json({ events: await listRaceEvents(env.DB, eventsRaceId) });
      }

      const stateRaceId = matchRacePath(url.pathname, "state");
      if (stateRaceId) {
        const state = await getRaceState(env.DB, stateRaceId);
        if (!state) {
          return Response.json({ error: "not_found" }, { status: 404 });
        }
        return Response.json(state);
      }
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  },
};
