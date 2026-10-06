import type { ReactNode } from "react";

export function AuthHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-1.5">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{title}</h1>
      {children && <p className="text-sm text-zinc-600 dark:text-zinc-400">{children}</p>}
    </div>
  );
}
