import { handleIngest } from "./ingest";
import type { Env } from "./types";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return Response.json({ status: "ok" });
    }
    if (url.pathname === "/api/ingest" && request.method === "POST") {
      return handleIngest(request, env);
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  },
};
