import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * API client for Client Components. Requests go to the same-origin `/api/*` proxy, so auth
 * cookies stay first-party and no CORS is needed.
 */
export const apiBrowser = createClient<paths>({ baseUrl: "/api" });
