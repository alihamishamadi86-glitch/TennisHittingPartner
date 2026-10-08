import { apiBrowser } from "@/lib/api/browser";

/** Actions taken from the sessions list (confirmation happens through payment). */
export type BookingAction = "cancel" | "complete" | "no_show";

/** Typed calls for each booking action endpoint. */
export function runBookingAction(bookingId: string, action: BookingAction, reason = "") {
  const path = { params: { path: { booking_id: bookingId } } };
  switch (action) {
    case "cancel":
      return apiBrowser.POST("/bookings/{booking_id}/cancel", { ...path, body: { reason } });
    case "complete":
      return apiBrowser.POST("/bookings/{booking_id}/complete", path);
    case "no_show":
      return apiBrowser.POST("/bookings/{booking_id}/no-show", path);
  }
}

export function bookingErrorMessage(error: unknown): string {
  const detail = (error as { detail?: { message?: string } | string } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  return detail?.message ?? "Something went wrong. Please try again.";
}
