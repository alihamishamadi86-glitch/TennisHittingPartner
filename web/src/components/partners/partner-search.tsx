"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import {
  formatSlotDay,
  formatSlotTime,
  upcomingDates,
  formatDate,
  type PartnerCard,
} from "@/lib/availability/format";
import { BACKGROUND_LABELS, NTRP_LEVELS, STYLE_LABELS, formatNtrp } from "@/lib/profile/labels";

export type SearchOrigin = {
  city: string;
  region: string;
  postal_code: string;
  country_code: string;
  level: number | null;
};

type Point = { lat: number; lon: number; label: string };
export type SearchView = "courts" | "area";
type CourtRef = { id: string; name: string };

const chip = (active: boolean) =>
  `whitespace-nowrap rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
    active
      ? "border-emerald-600 bg-emerald-600 text-white"
      : "border-zinc-300 text-zinc-700 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300"
  }`;

const COURT_RADII: [number, string][] = [
  [0, "Same courts only"],
  [2, "Within 2 km"],
  [5, "Within 5 km"],
  [10, "Within 10 km"],
];

export function PartnerSearch({
  origin,
  myCourts,
  initialView,
}: {
  origin: SearchOrigin | null;
  /** Players only: their saved courts, for suggestions at (or near) them. */
  myCourts: CourtRef[] | null;
  initialView: SearchView;
}) {
  const [view, setView] = useState<SearchView>(myCourts ? initialView : "area");
  const [courtRadius, setCourtRadius] = useState(5);
  const [point, setPoint] = useState<Point | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [duration, setDuration] = useState(60);
  const [minLevel, setMinLevel] = useState<number | null>(origin?.level ?? null);
  const [radius, setRadius] = useState(15);
  const [results, setResults] = useState<PartnerCard[] | null>(null);
  const [error, setError] = useState<string>();
  const dates = upcomingDates(14);

  // Resolve the player's home location once (city/postcode lookups are cached server-side).
  useEffect(() => {
    if (!origin) return;
    let active = true;
    apiBrowser
      .POST("/cities/discover", {
        body: {
          city: origin.city || null,
          region: origin.region || null,
          postal_code: origin.postal_code || null,
          country_code: origin.country_code,
        },
      })
      .then(({ data, error }) => {
        if (!active) return;
        if (!data) return setError(errorMessage(error));
        const focus = data.focus;
        setPoint(
          focus
            ? { lat: focus.lat, lon: focus.lon, label: focus.postal_code }
            : { lat: data.city.lat, lon: data.city.lon, label: data.city.name },
        );
      });
    return () => {
      active = false;
    };
  }, [origin]);

  const search = useCallback(async () => {
    setError(undefined);
    if (view === "courts") {
      if (!myCourts?.length) return setResults([]);
      const { data, error } = await apiBrowser.GET("/partners/suggested", {
        params: {
          query: {
            radius_km: courtRadius,
            duration,
            ...(day ? { date: day } : {}),
            ...(minLevel ? { min_level: minLevel } : {}),
          },
        },
      });
      if (data) setResults(data);
      else setError(errorMessage(error));
      return;
    }
    if (!point) return;
    const { data, error } = await apiBrowser.GET("/partners/search", {
      params: {
        query: {
          lat: point.lat,
          lon: point.lon,
          radius_km: radius,
          duration,
          ...(day ? { date: day } : {}),
          ...(minLevel ? { min_level: minLevel } : {}),
        },
      },
    });
    if (data) setResults(data);
    else setError(errorMessage(error));
  }, [view, myCourts, courtRadius, point, radius, duration, day, minLevel]);

  useEffect(() => {
    const timer = setTimeout(() => void search(), 0);
    return () => clearTimeout(timer);
  }, [search]);

  if (!origin) {
    return (
      <Alert>
        Add your city to your <Link href="/onboarding/profile" className="font-semibold underline">profile</Link> to find
        partners near you.
      </Alert>
    );
  }

  function switchView(next: SearchView) {
    if (next === view) return;
    setResults(null);
    setView(next);
  }

  return (
    <div className="flex flex-col gap-5">
      {myCourts && (
        <div className="flex w-fit rounded-xl border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900" role="tablist">
          {(
            [
              ["courts", `At my courts${myCourts.length ? ` (${myCourts.length})` : ""}`],
              ["area", "Near me"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              onClick={() => switchView(key)}
              className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                view === key
                  ? "bg-emerald-600 text-white"
                  : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {view === "courts" && myCourts?.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-zinc-300 p-6 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
          Save the courts you play at and we&apos;ll suggest partners who play there or close by.
          <Link href="/clubs" className="font-semibold text-emerald-700 hover:underline dark:text-emerald-400">
            Choose my courts →
          </Link>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="group" aria-label="Day">
              <button type="button" className={chip(day === null)} onClick={() => setDay(null)}>
                Any day
              </button>
              {dates.map((d) => (
                <button key={d} type="button" className={chip(day === d)} onClick={() => setDay(d)}>
                  {formatDate(d)}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-zinc-700 dark:text-zinc-300">
              <span className="flex items-center gap-2">
                Session
                {[60, 90].map((m) => (
                  <button key={m} type="button" className={chip(duration === m)} onClick={() => setDuration(m)}>
                    {m} min
                  </button>
                ))}
              </span>
              <label className="flex items-center gap-2">
                Level at least
                <select
                  value={minLevel ?? ""}
                  onChange={(e) => setMinLevel(e.target.value ? Number(e.target.value) : null)}
                  className="h-9 rounded-lg border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-900"
                >
                  <option value="">Any</option>
                  {NTRP_LEVELS.filter((l) => l >= 3).map((l) => (
                    <option key={l} value={l}>
                      {formatNtrp(l)}
                    </option>
                  ))}
                </select>
              </label>
              {view === "courts" && myCourts ? (
                <label className="flex items-center gap-2">
                  <select
                    aria-label="Distance from my courts"
                    value={courtRadius}
                    onChange={(e) => setCourtRadius(Number(e.target.value))}
                    className="h-9 rounded-lg border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-900"
                  >
                    {COURT_RADII.map(([km, label]) => (
                      <option key={km} value={km}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <span className="text-zinc-500">
                    of {myCourts.length === 1 ? myCourts[0].name : "my courts"} ·{" "}
                    <Link href="/courts" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
                      Edit
                    </Link>
                  </span>
                </label>
              ) : (
                <label className="flex items-center gap-2">
                  Within
                  <select
                    value={radius}
                    onChange={(e) => setRadius(Number(e.target.value))}
                    className="h-9 rounded-lg border border-zinc-300 bg-white px-2 dark:border-zinc-700 dark:bg-zinc-900"
                  >
                    {[5, 10, 15, 25, 50].map((km) => (
                      <option key={km} value={km}>
                        {km} km
                      </option>
                    ))}
                  </select>
                  {point && <span className="text-zinc-500">of {point.label}</span>}
                </label>
              )}
            </div>
          </div>

          {error && <Alert tone="error">{error}</Alert>}
          {results === null && !error && <p className="text-sm text-zinc-500">Finding partners…</p>}
          {results?.length === 0 && (
            <p className="rounded-xl border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
              No partners match yet. Try another day, a lower level or a wider area.
            </p>
          )}
          <ul className="grid gap-3">
            {results?.map((p) => (
              <li key={p.user_id}>
                <PartnerResult partner={p} day={day} duration={duration} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function PartnerResult({ partner, day, duration }: { partner: PartnerCard; day: string | null; duration: number }) {
  const facts = [
    partner.background ? BACKGROUND_LABELS[partner.background] : null,
    partner.play_style ? STYLE_LABELS[partner.play_style] : null,
    partner.years_playing ? `${partner.years_playing} yrs playing` : null,
  ].filter(Boolean);
  const club = partner.clubs[0];
  return (
    <Link
      href={`/partners/${partner.user_id}?duration=${duration}`}
      className="flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-4 transition-colors hover:border-emerald-600 sm:flex-row sm:gap-4 dark:border-zinc-800 dark:bg-zinc-900"
    >
      <Avatar src={partner.avatar_url} name={partner.full_name} size={64} />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-zinc-900 dark:text-zinc-50">{partner.full_name}</span>
          {partner.ntrp_rating && (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              NTRP {formatNtrp(partner.ntrp_rating)} · verified
            </span>
          )}
        </div>
        {facts.length > 0 && <p className="text-sm text-zinc-600 dark:text-zinc-400">{facts.join(" · ")}</p>}
        {club &&
          (club.near_court ? (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {club.distance_km === 0 ? (
                <span className="font-medium text-emerald-800 dark:text-emerald-300">Plays at your court {club.name}</span>
              ) : (
                `Plays at ${club.name} · ${club.distance_km} km from ${club.near_court}`
              )}
              {partner.clubs.length > 1 && ` +${partner.clubs.length - 1} more`}
            </p>
          ) : (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Plays at {club.name}
              {club.distance_km !== null && club.distance_km !== undefined && ` · ${club.distance_km} km`}
              {partner.clubs.length > 1 && ` +${partner.clubs.length - 1} more`}
            </p>
          ))}
        {day ? (
          partner.slots.length > 0 ? (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {partner.slots.slice(0, 8).map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium tabular-nums text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                >
                  {formatSlotTime(s, partner.timezone)}
                </span>
              ))}
              {partner.slots.length > 8 && <span className="text-xs text-zinc-500">+{partner.slots.length - 8}</span>}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">No open times that day.</p>
          )
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {partner.next_slot
              ? `Next available ${formatSlotDay(partner.next_slot, partner.timezone)}, ${formatSlotTime(partner.next_slot, partner.timezone)}`
              : "No open times in the next two weeks"}
          </p>
        )}
      </div>
    </Link>
  );
}
