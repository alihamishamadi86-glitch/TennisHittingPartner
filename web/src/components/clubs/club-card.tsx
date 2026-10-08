import type { ReactNode } from "react";

import type { Club } from "@/lib/clubs/types";
import { KIND_LABELS } from "@/lib/clubs/types";

const KIND_TONES = {
  club: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  sports_centre: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  public_courts: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
} as const;

const linkClass = "text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400";

/** Ways to reach the venue: book a court online, call, email, website. */
export function ClubContactLinks({
  club,
}: {
  club: { booking_url?: string | null; phone?: string | null; email?: string | null; website?: string | null };
}) {
  return (
    <>
      {club.booking_url && (
        <a href={club.booking_url} target="_blank" rel="noopener noreferrer" className="rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700">
          Book a court ↗
        </a>
      )}
      {club.phone && (
        <a href={`tel:${club.phone.replace(/\s+/g, "")}`} className={`${linkClass} tabular-nums`}>
          {club.phone}
        </a>
      )}
      {club.email && (
        <a href={`mailto:${club.email}`} className={linkClass}>
          Email
        </a>
      )}
      {club.website && (
        <a href={club.website} target="_blank" rel="noopener noreferrer" className={linkClass}>
          Website ↗
        </a>
      )}
    </>
  );
}

export function ClubCard({
  club,
  selected,
  onSelect,
  courtPick,
  extra,
  actions,
}: {
  club: Club;
  selected: boolean;
  onSelect: () => void;
  courtPick?: { checked: boolean; onToggle: () => void };
  /** Shown under the club details, e.g. who else plays here. */
  extra?: ReactNode;
  /** Extra controls in the right-hand column. */
  actions?: ReactNode;
}) {
  const facts = [
    club.court_count ? `${club.court_count} court${club.court_count === 1 ? "" : "s"}` : null,
    club.surface ? club.surface.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : null,
    club.lit ? "Floodlit" : null,
    club.access && club.access !== "yes" && club.access !== "public" ? `Access: ${club.access}` : null,
  ].filter(Boolean);

  return (
    <li
      id={`club-${club.id}`}
      className={`flex gap-3 rounded-xl border bg-white p-4 transition-colors dark:bg-zinc-900 ${
        selected ? "border-emerald-600 ring-2 ring-emerald-600/20" : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 flex-col gap-1.5 text-left">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-zinc-900 dark:text-zinc-50">{club.name}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${KIND_TONES[club.kind]}`}>{KIND_LABELS[club.kind]}</span>
        </span>
        {facts.length > 0 && <span className="text-sm text-zinc-600 dark:text-zinc-400">{facts.join(" · ")}</span>}
        {club.address && <span className="text-sm text-zinc-500">{club.address}</span>}
        {club.distance_km !== null && club.distance_km !== undefined && (
          <span className="text-xs text-zinc-500">{club.distance_km.toFixed(1)} km away</span>
        )}
        {extra}
      </button>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {courtPick && (
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <input type="checkbox" checked={courtPick.checked} onChange={courtPick.onToggle} className="h-4 w-4 accent-emerald-600" />
            I play here
          </label>
        )}
        <ClubContactLinks club={club} />
        {actions}
      </div>
    </li>
  );
}
