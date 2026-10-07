import { NextResponse, type NextRequest } from "next/server";

/**
 * Protected pages need a valid access cookie. When it has expired (15 min), redirect through
 * the API's session renewal, which sees the path-scoped refresh cookie, rotates the session and
 * redirects back — or on to /login when there is no session. Pages still verify the user
 * server-side; this only avoids rendering them without credentials.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has("thp_access")) return NextResponse.next();

  const renew = request.nextUrl.clone();
  renew.pathname = "/api/auth/session/renew";
  renew.search = new URLSearchParams({
    next: `${request.nextUrl.pathname}${request.nextUrl.search}`,
  }).toString();
  return NextResponse.redirect(renew);
}

export const config = {
  matcher: ["/dashboard/:path*", "/onboarding/:path*", "/admin/:path*", "/clubs/:path*"],
};
