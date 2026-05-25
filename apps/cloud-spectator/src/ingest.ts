import { hasValidBearerToken } from "./auth";
import type { Env } from "./types";

export async function handleIngest(request: Request, env: Env): Promise<Response> {
  if (!(await hasValidBearerToken(request, env.INGEST_TOKEN))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  return Response.json({ status: "accepted" }, { status: 202 });
}
