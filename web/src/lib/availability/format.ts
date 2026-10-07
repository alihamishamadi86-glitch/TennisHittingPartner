import type { components } from "@/lib/api/schema";

export type Availability = components["schemas"]["AvailabilityOut"];
export type WeeklyWindow = components["schemas"]["WeeklyWindowIn"];
export type AvailabilityException = components["schemas"]["ExceptionOut"];
export type Slots = components["schemas"]["SlotsOut"];
export type PartnerCard = components["schemas"]["PartnerCardOut"];
export type PartnerPublic = components["schemas"]["PartnerPublicOut"];

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** "08:00" in the partner's timezone, with the zone abbreviation when it differs from the viewer's. */
export function formatSlotTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(iso));
}

export function formatSlotDay(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone }).format(
    new Date(iso),
  );
}

export function formatDate(isoDate: string): string {
  // Plain calendar date (no timezone shift).
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

export function zoneLabel(timeZone: string): string {
  const part = new Intl.DateTimeFormat(undefined, { timeZone, timeZoneName: "short" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? timeZone;
}

export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export function allTimeZones(): string[] {
  return typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [browserTimeZone()];
}

/** Local calendar dates (YYYY-MM-DD) for the next `count` days in the viewer's timezone. */
export function upcomingDates(count: number): string[] {
  const today = new Date();
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
}
