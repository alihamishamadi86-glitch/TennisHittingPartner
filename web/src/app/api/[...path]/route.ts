import type { NextRequest } from "next/server";

import { apiInternalUrl } from "@/lib/api/server";

// Same-origin proxy: /api/<path> → FastAPI /<path>. Keeps auth cookies first-party.

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

async function proxy(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = new URL(path.map(encodeURIComponent).join("/"), `${apiInternalUrl()}/`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key)) headers.set(key, value);
  });
  headers.set("x-forwarded-host", request.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });

  const responseHeaders = new Headers(upstream.headers);
  // fetch() already decoded the body; forwarding these would corrupt the response.
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  // Rewrite absolute redirects to the internal API host so they stay behind the proxy.
  const location = upstream.headers.get("location");
  if (location?.startsWith(apiInternalUrl())) {
    responseHeaders.set("location", `/api${location.slice(apiInternalUrl().length)}`);
  }

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export {
  proxy as DELETE,
  proxy as GET,
  proxy as HEAD,
  proxy as OPTIONS,
  proxy as PATCH,
  proxy as POST,
  proxy as PUT,
};
