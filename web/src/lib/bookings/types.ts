import type { components } from "@/lib/api/schema";

export type Booking = components["schemas"]["BookingOut"];
export type BookingStatus = components["schemas"]["BookingStatus"];
export type Waiver = components["schemas"]["WaiverOut"];

export const STATUS_LABELS: Record<BookingStatus, string> = {
  held: "Awaiting payment",
  confirmed: "Confirmed",
  completed: "Completed",
  expired: "Expired",
  cancelled_free: "Cancelled",
  cancelled_late: "Cancelled (late)",
  partner_cancelled: "Cancelled by partner",
  rained_out: "Rained out",
  no_show: "No-show",
};

export const STATUS_TONES: Record<BookingStatus, string> = {
  held: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  confirmed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  completed: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  expired: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  cancelled_free: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  cancelled_late: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  partner_cancelled: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  rained_out: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  no_show: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function formatSession(startIso: string, endIso: string, timeZone: string): string {
  const day = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", timeZone }).format(
    new Date(startIso),
  );
  const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone });
  return `${day}, ${time.format(new Date(startIso))}–${time.format(new Date(endIso))}`;
}

export function formatMoment(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

export function mapsLink(lat: number, lon: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}`;
}
