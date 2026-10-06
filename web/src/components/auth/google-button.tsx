import { buttonClasses } from "@/components/ui/button";

export function GoogleButton({ role, next, label = "Continue with Google" }: { role?: string; next?: string; label?: string }) {
  const params = new URLSearchParams();
  if (role) params.set("role", role);
  if (next) params.set("next", next);
  const query = params.toString();
  return (
    // A full navigation (not fetch): the API redirects to Google and back.
    <a href={`/api/auth/google/login${query ? `?${query}` : ""}`} className={buttonClasses("secondary", "w-full")}>
      <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4">
        <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.6 3.8-5.5 3.8-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.2 14.6 2.2 12 2.2 6.6 2.2 2.2 6.6 2.2 12s4.4 9.8 9.8 9.8c5.7 0 9.4-4 9.4-9.6 0-.6-.1-1.1-.2-1.6H12z" />
      </svg>
      {label}
    </a>
  );
}

export function Divider() {
  return (
    <div className="flex items-center gap-3 text-xs uppercase tracking-wider text-zinc-400">
      <span className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
      or
      <span className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
    </div>
  );
}
