import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiServer } from "@/lib/api/server";

import type { User } from "./types";

/** API client that acts as the signed-in user by forwarding the browser's cookies. */
export async function authedApi() {
  const cookieHeader = (await cookies()).toString();
  const client = apiServer();
  client.use({
    onRequest({ request }) {
      if (cookieHeader) request.headers.set("cookie", cookieHeader);
      return request;
    },
  });
  return client;
}

/** The signed-in user for this request, or null. */
export async function getCurrentUser(): Promise<User | null> {
  if (!(await cookies()).size) return null;
  const { data } = await (await authedApi()).GET("/me");
  return data ?? null;
}

/**
 * Require a signed-in user. When the access token is missing/expired, bounce through the API's
 * session renewal (which can see the path-scoped refresh cookie) and come back to `returnTo`.
 */
export async function requireUser(returnTo: string): Promise<User> {
  const user = await getCurrentUser();
  if (!user) redirect(`/api/auth/session/renew?next=${encodeURIComponent(returnTo)}`);
  return user;
}

export async function googleSignInEnabled(): Promise<boolean> {
  try {
    const { data } = await apiServer().GET("/auth/providers");
    return data?.google ?? false;
  } catch {
    return false;
  }
}
