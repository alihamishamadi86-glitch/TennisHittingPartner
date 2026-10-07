import type { Club } from "@/lib/clubs/types";
import { KIND_LABELS } from "@/lib/clubs/types";

const KIND_TONES = {
  club: "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  sports_centre: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  public_courts: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
} as const;

export function ClubCard({
  club,
  selected,
  onSelect,
  partnerPick,
}: {
  club: Club;
  selected: boolean;
  onSelect: () => void;
  partnerPick?: { checked: boolean; onToggle: () => void };
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
      </button>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {partnerPick && (
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <input type="checkbox" checked={partnerPick.checked} onChange={partnerPick.onToggle} className="h-4 w-4 accent-emerald-600" />
            I play here
          </label>
        )}
        {club.website && (
          <a href={club.website} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
            Website ↗
          </a>
        )}
      </div>
    </li>
  );
}
