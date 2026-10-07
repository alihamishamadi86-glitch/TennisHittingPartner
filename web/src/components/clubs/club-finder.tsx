"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import type { City, Club, ClubKind, MapTiles } from "@/lib/clubs/types";
import { COUNTRIES } from "@/lib/profile/labels";

import { ClubCard } from "./club-card";

// Leaflet touches `window`, so the map only renders in the browser.
const ClubMap = dynamic(() => import("./club-map"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-zinc-200 dark:bg-zinc-800" />,
});

const POLL_MS = 2500;
const POLL_LIMIT_MS = 3 * 60 * 1000;
type KindFilter = "all" | "venues" | ClubKind;

export type Location = { city: string; region: string; country_code: string };

export function ClubFinder({
  initialLocation,
  tiles,
  partnerClubIds,
}: {
  initialLocation: Location | null;
  tiles: MapTiles;
  /** Present for partners: the clubs they already play at. */
  partnerClubIds?: string[];
}) {
  const [location, setLocation] = useState<Location>(initialLocation ?? { city: "", region: "", country_code: "US" });
  const [city, setCity] = useState<City | null>(null);
  const [clubs, setClubs] = useState<Club[]>([]);
  const [error, setError] = useState<string>();
  const [searching, setSearching] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [picked, setPicked] = useState<Set<string>>(new Set(partnerClubIds ?? []));
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const searchToken = useRef(0);

  const loadClubs = useCallback(async (cityId: string) => {
    const { data } = await apiBrowser.GET("/clubs", { params: { query: { city_id: cityId } } });
    setClubs(data ?? []);
  }, []);

  const search = useCallback(
    async (target: Location) => {
      const token = ++searchToken.current;
      setSearching(true);
      setError(undefined);
      setSelectedId(null);
      const { data, error } = await apiBrowser.POST("/cities/discover", {
        body: { city: target.city.trim(), region: target.region.trim() || null, country_code: target.country_code },
      });
      if (!data) {
        setError(errorMessage(error));
        setSearching(false);
        return;
      }
      let current = data;
      setCity(current);
      // Show what we already have (e.g. during a refresh) while discovery runs.
      if (current.club_count > 0) await loadClubs(current.id);

      const started = Date.now();
      while (current.status === "pending" || current.status === "running") {
        if (Date.now() - started > POLL_LIMIT_MS) {
          setError("This is taking longer than usual. Check back in a few minutes.");
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (token !== searchToken.current) return; // a newer search started
        const next = await apiBrowser.GET("/cities/{city_id}", { params: { path: { city_id: current.id } } });
        if (!next.data) break;
        current = next.data;
        setCity(current);
      }
      if (token !== searchToken.current) return;
      if (current.status === "failed" && current.club_count === 0) {
        setError("We couldn't load courts for this city right now. Please try again later.");
      }
      await loadClubs(current.id);
      setSearching(false);
    },
    [loadClubs],
  );

  // Search the user's home city on arrival. Scheduled (not called inline) so state updates
  // happen outside the effect body, and StrictMode's double-mount cancels the duplicate.
  useEffect(() => {
    if (!initialLocation?.city) return;
    const timer = setTimeout(() => void search(initialLocation), 0);
    return () => clearTimeout(timer);
  }, [initialLocation, search]);

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return clubs.filter((club) => {
      if (q && !club.name.toLowerCase().includes(q) && !(club.address ?? "").toLowerCase().includes(q)) return false;
      if (kind === "venues") return club.kind !== "public_courts";
      if (kind !== "all") return club.kind === kind;
      return true;
    });
  }, [clubs, filter, kind]);

  function select(id: string) {
    setSelectedId(id);
    document.getElementById(`club-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function togglePick(id: string) {
    setSaveState("idle");
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function savePicks() {
    setSaveState("saving");
    const { error } = await apiBrowser.PUT("/me/partner-clubs", { body: { club_ids: [...picked] } });
    if (error) {
      setError(errorMessage(error));
      setSaveState("idle");
    } else {
      setSaveState("saved");
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (location.city.trim()) void search(location);
  }

  const center: [number, number] = city ? [city.lat, city.lon] : [39.5, -98.35];
  const isPartner = partnerClubIds !== undefined;

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end">
        <Field id="city" label="City" value={location.city} onChange={(e) => setLocation({ ...location, city: e.target.value })} required />
        <Field id="region" label="State" value={location.region} onChange={(e) => setLocation({ ...location, region: e.target.value })} />
        <Select id="country_code" label="Country" options={COUNTRIES} value={location.country_code} onChange={(e) => setLocation({ ...location, country_code: e.target.value })} />
        <Button type="submit" disabled={searching || !location.city.trim()}>
          {searching ? "Searching…" : "Find courts"}
        </Button>
      </form>

      {error && <Alert tone="error">{error}</Alert>}
      {searching && city && (city.status === "pending" || city.status === "running") && (
        <Alert>
          Finding tennis courts in {city.name}… The first search for a city can take up to a minute.
        </Alert>
      )}

      {city && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="order-2 flex min-w-0 flex-col gap-3 lg:order-1">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                <strong className="text-zinc-900 dark:text-zinc-50">{visible.length}</strong> places in {city.name}
                {city.region ? `, ${city.region}` : ""}
              </p>
              <div className="flex gap-2">
                <input
                  type="search"
                  placeholder="Filter by name"
                  aria-label="Filter by name"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="h-9 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm outline-none focus:border-emerald-600 sm:w-44 dark:border-zinc-700 dark:bg-zinc-900"
                />
                <select
                  aria-label="Type"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as KindFilter)}
                  className="h-9 rounded-lg border border-zinc-300 bg-white px-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                >
                  <option value="all">All</option>
                  <option value="venues">Clubs & centres</option>
                  <option value="public_courts">Public courts</option>
                </select>
              </div>
            </div>
            {isPartner && (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-900/60 dark:bg-emerald-950/30">
                <p className="text-sm text-emerald-900 dark:text-emerald-200">
                  {picked.size === 0 ? "Tick the places you can play at." : `${picked.size} selected`}
                </p>
                <Button type="button" onClick={savePicks} disabled={saveState === "saving"}>
                  {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved ✓" : "Save my clubs"}
                </Button>
              </div>
            )}
            <ul className="flex max-h-[70vh] flex-col gap-2 overflow-y-auto pr-1">
              {visible.map((club) => (
                <ClubCard
                  key={club.id}
                  club={club}
                  selected={club.id === selectedId}
                  onSelect={() => setSelectedId(club.id)}
                  partnerPick={isPartner ? { checked: picked.has(club.id), onToggle: () => togglePick(club.id) } : undefined}
                />
              ))}
              {!searching && visible.length === 0 && (
                <li className="rounded-xl border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
                  No courts found{filter || kind !== "all" ? " for these filters" : ""}.
                </li>
              )}
            </ul>
            <p className="text-xs text-zinc-500">
              Court data © OpenStreetMap contributors (ODbL). Something missing? Add it on openstreetmap.org.
            </p>
          </div>
          <div className="order-1 h-72 overflow-hidden rounded-xl border border-zinc-200 sm:h-96 lg:sticky lg:top-4 lg:order-2 lg:h-[70vh] dark:border-zinc-800">
            <ClubMap clubs={visible} center={center} tiles={tiles} selectedId={selectedId} onSelect={select} />
          </div>
        </div>
      )}
    </div>
  );
}
