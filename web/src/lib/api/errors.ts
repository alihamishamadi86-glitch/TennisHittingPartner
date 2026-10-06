type ValidationIssue = { loc?: (string | number)[]; msg?: string };

const FIELD_LABELS: Record<string, string> = {
  email: "Email",
  password: "Password",
  full_name: "Name",
  role: "Role",
};

/** Turn a FastAPI error body into a message fit for the UI. */
export function errorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
  if (!error || typeof error !== "object" || !("detail" in error)) return fallback;
  const { detail } = error as { detail: unknown };
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const issue = detail[0] as ValidationIssue;
    const field = issue.loc?.at(-1);
    const label = typeof field === "string" ? FIELD_LABELS[field] : undefined;
    const msg = (issue.msg ?? "").replace(/^Value error, /, "");
    return label ? `${label}: ${msg}` : msg || fallback;
  }
  return fallback;
}
