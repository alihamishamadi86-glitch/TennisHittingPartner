"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import {
  WEEKDAYS,
  allTimeZones,
  browserTimeZone,
  formatDate,
  type Availability,
  type Slots,
  type WeeklyWindow,
} from "@/lib/availability/format";

import { SlotPreview } from "./slot-preview";

const timeInput =
  "h-10 rounded-lg border border-zinc-300 bg-white px-2 text-sm tabular-nums outline-none focus:border-emerald-600 dark:border-zinc-700 dark:bg-zinc-900";

export function AvailabilityEditor({ initial, initialPreview }: { initial: Availability; initialPreview: Slots | null }) {
  const [timezone, setTimezone] = useState(initial.timezone ?? browserTimeZone());
  const [windows, setWindows] = useState<WeeklyWindow[]>(initial.windows);
  const [exceptions, setExceptions] = useState(initial.exceptions);
  const [preview, setPreview] = useState(initialPreview);
  const [status, setStatus] = useState<{ tone: "error" | "success"; text: string }>();
  const [saving, setSaving] = useState(false);

  async function refreshPreview() {
    const { data } = await apiBrowser.GET("/me/availability/preview", { params: { query: { days: 7 } } });
    setPreview(data ?? null);
  }

  function update(index: number, patch: Partial<WeeklyWindow>) {
    setWindows(windows.map((w, i) => (i === index ? { ...w, ...patch } : w)));
  }

  function copyToWeekdays(weekday: number) {
    const source = windows.filter((w) => w.weekday === weekday);
    const others = windows.filter((w) => w.weekday > 4 || w.weekday === weekday);
    const copies = [0, 1, 2, 3, 4].filter((d) => d !== weekday).flatMap((d) => source.map((w) => ({ ...w, weekday: d })));
    setWindows([...others, ...copies]);
  }

  async function save() {
    setSaving(true);
    setStatus(undefined);
    const { data, error } = await apiBrowser.PUT("/me/availability", { body: { timezone, windows } });
    setSaving(false);
    if (!data) {
      setStatus({ tone: "error", text: errorMessage(error) });
      return;
    }
    setWindows(data.windows);
    setStatus({ tone: "success", text: "Weekly hours saved." });
    await refreshPreview();
  }

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Weekly hours</h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            When you&apos;re generally free to hit. Clients can book 60- or 90-minute sessions inside these windows, at
            least 12 hours ahead.
          </p>
        </div>
        <div className="max-w-sm">
          <Select
            id="timezone"
            label="Timezone"
            options={allTimeZones().map((z) => [z, z.replace(/_/g, " ")])}
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
        </div>
        <ul className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800">
          {WEEKDAYS.map((label, weekday) => {
            const rows = windows.map((w, i) => ({ w, i })).filter(({ w }) => w.weekday === weekday);
            return (
              <li key={label} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:gap-4">
                <span className="w-28 shrink-0 pt-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">{label}</span>
                <div className="flex flex-1 flex-col gap-2">
                  {rows.length === 0 && <span className="pt-2 text-sm text-zinc-400">Unavailable</span>}
                  {rows.map(({ w, i }) => (
                    <div key={i} className="flex items-center gap-2">
                      <input
                        type="time"
                        step={900}
                        aria-label={`${label} start`}
                        value={w.start}
                        onChange={(e) => update(i, { start: e.target.value })}
                        className={timeInput}
                      />
                      <span className="text-zinc-400">–</span>
                      <input
                        type="time"
                        step={900}
                        aria-label={`${label} end`}
                        value={w.end === "24:00" ? "23:59" : w.end}
                        onChange={(e) => update(i, { end: e.target.value === "23:59" ? "24:00" : e.target.value })}
                        className={timeInput}
                      />
                      <button
                        type="button"
                        onClick={() => setWindows(windows.filter((_, j) => j !== i))}
                        className="rounded-lg px-2 py-1 text-sm text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800"
                        aria-label={`Remove ${label} ${w.start}–${w.end}`}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2 sm:pt-1">
                  <button
                    type="button"
                    onClick={() => setWindows([...windows, { weekday, start: "08:00", end: "10:00" }])}
                    className="text-sm font-semibold text-emerald-700 hover:underline dark:text-emerald-400"
                  >
                    + Add hours
                  </button>
                  {weekday < 5 && rows.length > 0 && (
                    <button
                      type="button"
                      onClick={() => copyToWeekdays(weekday)}
                      className="text-sm text-zinc-500 hover:underline"
                    >
                      Copy to weekdays
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {status && <Alert tone={status.tone}>{status.text}</Alert>}
        <Button type="button" onClick={save} disabled={saving} className="w-fit">
          {saving ? "Saving…" : "Save weekly hours"}
        </Button>
      </section>

      <ExceptionsSection
        exceptions={exceptions}
        disabled={!initial.timezone && !preview}
        onChange={async (next) => {
          setExceptions(next);
          await refreshPreview();
        }}
      />

      <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">What clients see</h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Bookable 60-minute start times for the next 7 days.</p>
        </div>
        {preview ? <SlotPreview slots={preview} /> : <p className="text-sm text-zinc-500">Save your weekly hours to see a preview.</p>}
      </section>
    </div>
  );
}

const KIND_OPTIONS: [string, string][] = [
  ["off", "Day off"],
  ["block", "Unavailable for some hours"],
  ["extra", "Extra hours"],
];

function ExceptionsSection({
  exceptions,
  disabled,
  onChange,
}: {
  exceptions: Availability["exceptions"];
  disabled: boolean;
  onChange: (next: Availability["exceptions"]) => Promise<void>;
}) {
  const [kind, setKind] = useState("off");
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const withTimes = kind !== "off";
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/me/availability/exceptions", {
      body: {
        date: String(form.get("date")),
        kind: kind === "extra" ? "available" : "unavailable",
        start: withTimes ? String(form.get("start")) : null,
        end: withTimes ? String(form.get("end")) : null,
        note: String(form.get("note") ?? ""),
      },
    });
    setPending(false);
    if (!data) {
      setError(errorMessage(error));
      return;
    }
    event.currentTarget?.reset();
    await onChange(data.exceptions);
  }

  async function remove(id: string) {
    await apiBrowser.DELETE("/me/availability/exceptions/{exception_id}", { params: { path: { exception_id: id } } });
    await onChange(exceptions.filter((e) => e.id !== id));
  }

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Days off & changes</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">One-off changes to your weekly hours.</p>
      </div>
      {exceptions.length > 0 && (
        <ul className="flex flex-col gap-2">
          {exceptions.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 rounded-lg bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-950">
              <span>
                <strong className="font-medium">{formatDate(e.date)}</strong> ·{" "}
                {e.kind === "available"
                  ? `Extra hours ${e.start}–${e.end}`
                  : e.start
                    ? `Unavailable ${e.start}–${e.end}`
                    : "Day off"}
                {e.note && <span className="text-zinc-500"> · {e.note}</span>}
              </span>
              <button type="button" onClick={() => remove(e.id)} className="text-sm text-zinc-500 hover:text-red-600">
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {disabled ? (
        <p className="text-sm text-zinc-500">Save your weekly hours first.</p>
      ) : (
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1.4fr_auto_auto_1.4fr_auto] lg:items-end">
          <Field id="date" label="Date" type="date" required />
          <Select id="kind" label="Change" options={KIND_OPTIONS} value={kind} onChange={(e) => setKind(e.target.value)} />
          {kind !== "off" && (
            <>
              <Field id="start" label="From" type="time" step={900} defaultValue="08:00" required />
              <Field id="end" label="To" type="time" step={900} defaultValue="10:00" required />
            </>
          )}
          <Field id="note" label="Note (optional)" maxLength={200} />
          <Button type="submit" disabled={pending}>
            {pending ? "Adding…" : "Add"}
          </Button>
        </form>
      )}
      {error && <Alert tone="error">{error}</Alert>}
    </section>
  );
}
