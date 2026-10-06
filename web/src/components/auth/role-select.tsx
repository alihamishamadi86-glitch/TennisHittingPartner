"use client";

import type { SelfServiceRole } from "@/lib/auth/types";

const ROLES: { value: SelfServiceRole; title: string; description: string }[] = [
  { value: "client", title: "I'm a player", description: "Book hitting sessions with skilled partners." },
  { value: "partner", title: "I'm a hitting partner", description: "Offer sessions and earn on your schedule." },
];

export function RoleSelect({ value, onChange }: { value: SelfServiceRole | null; onChange: (role: SelfServiceRole) => void }) {
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="sr-only">Account type</legend>
      {ROLES.map((role) => {
        const selected = value === role.value;
        return (
          <label
            key={role.value}
            className={`flex cursor-pointer flex-col gap-1 rounded-xl border p-4 transition-colors ${
              selected
                ? "border-emerald-600 bg-emerald-50 ring-2 ring-emerald-600/20 dark:bg-emerald-950/30"
                : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-800 dark:hover:border-zinc-700"
            }`}
          >
            <input
              type="radio"
              name="role"
              value={role.value}
              checked={selected}
              onChange={() => onChange(role.value)}
              className="sr-only"
            />
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{role.title}</span>
            <span className="text-sm text-zinc-600 dark:text-zinc-400">{role.description}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
