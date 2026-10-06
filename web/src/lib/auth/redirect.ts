/** Same-site relative paths only; mirrors the API's open-redirect guard. */
export function safeNextPath(value: string | string[] | undefined, fallback = "/dashboard"): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return fallback;
  }
  return value;
}
