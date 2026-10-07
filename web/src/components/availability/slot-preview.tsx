import Link from "next/link";

import { formatDate, formatSlotTime, type Slots } from "@/lib/availability/format";

export function SlotPreview({
  slots,
  emptyText,
  bookingHref,
}: {
  slots: Slots;
  emptyText?: string;
  /** When given, each time links to booking it. */
  bookingHref?: (slotIso: string) => string;
}) {
  const any = slots.days.some((d) => d.slots.length > 0);
  if (!any) return <p className="text-sm text-zinc-500">{emptyText ?? "No open times in this period."}</p>;
  return (
    <ul className="flex flex-col gap-3">
      {slots.days.map((day) => (
        <li key={day.date} className="flex flex-col gap-1.5 sm:flex-row sm:gap-4">
          <span className="w-28 shrink-0 text-sm font-medium text-zinc-700 dark:text-zinc-300">{formatDate(day.date)}</span>
          {day.slots.length === 0 ? (
            <span className="text-sm text-zinc-400">—</span>
          ) : (
            <span className="flex flex-wrap gap-1.5">
              {day.slots.map((slot) =>
                bookingHref ? (
                  <Link
                    key={slot}
                    href={bookingHref(slot)}
                    className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-semibold tabular-nums text-white hover:bg-emerald-700"
                  >
                    {formatSlotTime(slot, slots.timezone)}
                  </Link>
                ) : (
                  <span
                    key={slot}
                    className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium tabular-nums text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                  >
                    {formatSlotTime(slot, slots.timezone)}
                  </span>
                ),
              )}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
