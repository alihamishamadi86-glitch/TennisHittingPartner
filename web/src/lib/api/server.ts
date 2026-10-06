import "server-only";

import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * API client for Server Components, Server Actions and Route Handlers.
 * Talks to the FastAPI service directly over the internal URL, read at request time so one
 * built image can be promoted across environments.
 */
export function apiServer() {
  return createClient<paths>({ baseUrl: apiInternalUrl(), cache: "no-store" });
}

export function apiInternalUrl(): string {
  return process.env.API_INTERNAL_URL ?? "http://localhost:8000";
}
