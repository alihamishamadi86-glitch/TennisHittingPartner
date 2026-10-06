import Link from "next/link";

export function Logo() {
  return (
    <Link href="/" className="inline-flex items-center gap-2 text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
      <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-emerald-600 text-white">
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M5.5 5.5c3.5 3 3.5 10 0 13M18.5 5.5c-3.5 3-3.5 10 0 13" />
        </svg>
      </span>
      Tennis Hitting Partner
    </Link>
  );
}
