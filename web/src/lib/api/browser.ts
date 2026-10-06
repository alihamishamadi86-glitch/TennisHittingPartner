import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * On a 401 (expired access cookie), refresh the session once and retry. Auth endpoints are
 * excluded so a failed login doesn't trigger a refresh loop.
 */
async function fetchWithRefresh(request: Request): Promise<Response> {
  const retry = request.clone();
  const response = await fetch(request);
  if (response.status !== 401 || new URL(request.url).pathname.startsWith("/api/auth/")) {
    return response;
  }
  const refreshed = await fetch("/api/auth/refresh", { method: "POST" });
  return refreshed.ok ? fetch(retry) : response;
}

/**
 * API client for Client Components. Requests go to the same-origin `/api/*` proxy, so auth
 * cookies stay first-party and no CORS is needed.
 */
export const apiBrowser = createClient<paths>({ baseUrl: "/api", fetch: fetchWithRefresh });
