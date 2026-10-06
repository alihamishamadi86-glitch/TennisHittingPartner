# web

Next.js 16 frontend. See the root [README](../README.md) for local setup.

- `src/lib/api/server.ts` — typed client for Server Components (calls `API_INTERNAL_URL`).
- `src/lib/api/browser.ts` — typed client for Client Components (calls the `/api/*` proxy).
- `src/app/api/[...path]/route.ts` — same-origin proxy to FastAPI, so auth cookies are first-party.
- `npm run gen:api` — regenerate `src/lib/api/schema.d.ts` from the API's OpenAPI schema.

Next.js 16 differs from older versions (e.g. `middleware` is now `proxy`); consult
`node_modules/next/dist/docs/` before using unfamiliar APIs.
