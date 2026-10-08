"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { buttonClasses } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import type { MapTiles, MyClub } from "@/lib/clubs/types";

import { ClubCard } from "./club-card";

const ClubMap = dynamic(() => import("./club-map"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-zinc-200 dark:bg-zinc-800" />,
});

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function whoPlaysHere(club: MyClub, role: "client" | "partner"): string {
  if (role === "client") {
    return club.partner_count
      ? `${plural(club.partner_count, "hitting partner plays", "hitting partners play")} here`
      : "No hitting partners here yet";
  }
  const players = club.player_count ? plural(club.player_count, "player calls", "players call") + " this their court" : null;
  const partners = club.partner_count ? plural(club.partner_count, "other partner", "other partners") : null;
  return [players, partners].filter(Boolean).join(" · ") || "No players have saved this court yet";
}

export function MyCourts({
  role,
  initialClubs,
  tiles,
}: {
  role: "client" | "partner";
  initialClubs: MyClub[];
  tiles: MapTiles;
}) {
  const [clubs, setClubs] = useState(initialClubs);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [removed, setRemoved] = useState<MyClub | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();

  const center = useMemo<[number, number]>(
    () =>
      clubs.length
        ? [clubs.reduce((sum, c) => sum + c.lat, 0) / clubs.length, clubs.reduce((sum, c) => sum + c.lon, 0) / clubs.length]
        : [39.5, -98.35],
    [clubs],
  );

  async function save(ids: string[]): Promise<boolean> {
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.PUT("/me/clubs", { body: { club_ids: ids } });
    setPending(false);
    if (!data) {
      setError(errorMessage(error));
      return false;
    }
    setClubs(data.clubs);
    return true;
  }

  async function remove(club: MyClub) {
    if (await save(clubs.filter((c) => c.id !== club.id).map((c) => c.id))) setRemoved(club);
  }

  async function undo() {
    if (removed && (await save([...clubs.map((c) => c.id), removed.id]))) setRemoved(null);
  }

  if (clubs.length === 0 && !removed) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-2xl border border-dashed border-zinc-300 p-10 text-center dark:border-zinc-700">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {role === "partner"
            ? "You haven't chosen any courts yet. Clients can only book you at courts you've added."
            : "You haven't saved any courts yet. Add the places you play and we'll suggest partners there."}
        </p>
        <Link href="/clubs" className={buttonClasses("primary")}>
          Find courts
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert tone="error">{error}</Alert>}
      {removed && (
        <Alert>
          Removed {removed.name}.{" "}
          <button type="button" onClick={undo} disabled={pending} className="font-semibold underline">
            Undo
          </button>
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="order-2 flex min-w-0 flex-col gap-3 lg:order-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              <strong className="text-zinc-900 dark:text-zinc-50">{clubs.length}</strong> {clubs.length === 1 ? "court" : "courts"}
            </p>
            <div className="flex gap-2">
              {role === "client" && clubs.length > 0 && (
                <Link href="/partners?view=courts" className={buttonClasses("primary", "h-9")}>
                  Find partners at my courts
                </Link>
              )}
              <Link href="/clubs" className={buttonClasses("secondary", "h-9")}>
                Add courts
              </Link>
            </div>
          </div>
          <ul className="flex flex-col gap-2">
            {clubs.map((club) => (
              <ClubCard
                key={club.id}
                club={club}
                selected={club.id === selectedId}
                onSelect={() => setSelectedId(club.id)}
                extra={
                  <span className="text-sm font-medium text-emerald-800 dark:text-emerald-300">{whoPlaysHere(club, role)}</span>
                }
                actions={
                  <button
                    type="button"
                    onClick={() => remove(club)}
                    disabled={pending}
                    className="text-sm font-medium text-zinc-500 hover:text-red-700 hover:underline disabled:opacity-50 dark:hover:text-red-400"
                  >
                    Remove
                  </button>
                }
              />
            ))}
          </ul>
        </div>
        <div className="order-1 h-64 overflow-hidden rounded-xl border border-zinc-200 sm:h-80 lg:sticky lg:top-4 lg:order-2 lg:h-[60vh] dark:border-zinc-800">
          <ClubMap
            clubs={clubs}
            center={center}
            focus={null}
            tiles={tiles}
            selectedId={selectedId}
            onSelect={(id) => {
              setSelectedId(id);
              document.getElementById(`club-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }}
          />
        </div>
      </div>
    </div>
  );
}
