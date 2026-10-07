import { NextResponse, type NextRequest } from "next/server";

import { PATH_HEADER } from "@/lib/auth/path-header";

/**
 * Protected pages need a valid access cookie. When it has expired (15 min), redirect through
 * the API's session renewal, which sees the path-scoped refresh cookie, rotates the session and
 * redirects back — or on to /login when there is no session. Pages still verify the user
 * server-side; this only avoids rendering them without credentials.
 */
export function proxy(request: NextRequest) {
  const path = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (request.cookies.has("thp_access")) {
    // Layouts can't see the URL; pass it so they can send people back to the right page.
    const headers = new Headers(request.headers);
    headers.set(PATH_HEADER, path);
    return NextResponse.next({ request: { headers } });
  }

  const renew = request.nextUrl.clone();
  renew.pathname = "/api/auth/session/renew";
  renew.search = new URLSearchParams({ next: path }).toString();
  return NextResponse.redirect(renew);
}

export const config = {
  matcher: ["/dashboard/:path*", "/onboarding/:path*", "/admin/:path*", "/clubs/:path*", "/availability/:path*", "/partners/:path*", "/book/:path*", "/sessions/:path*"],
};
