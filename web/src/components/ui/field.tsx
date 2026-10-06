import type { InputHTMLAttributes } from "react";

export function Field({
  label,
  hint,
  id,
  ...input
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; id: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
        {label}
      </label>
      <input
        id={id}
        name={id}
        className="h-11 rounded-lg border border-zinc-300 bg-white px-3 text-base text-zinc-900 outline-none transition-shadow placeholder:text-zinc-400 focus:border-emerald-600 focus:ring-2 focus:ring-emerald-600/20 sm:text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        aria-describedby={hint ? `${id}-hint` : undefined}
        {...input}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-zinc-500 dark:text-zinc-400">
          {hint}
        </p>
      )}
    </div>
  );
}
