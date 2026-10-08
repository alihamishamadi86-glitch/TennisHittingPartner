"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { bookingErrorMessage, runBookingAction, type BookingAction } from "@/lib/bookings/actions";
import {
  STATUS_LABELS,
  STATUS_TONES,
  formatMoment,
  formatSession,
  mapsLink,
  type Booking,
} from "@/lib/bookings/types";
import { formatMoney } from "@/lib/payments/money";
import { formatNtrp } from "@/lib/profile/labels";


export function SessionCard({ booking, viewer }: { booking: Booking; viewer: "client" | "partner" }) {
  const router = useRouter();
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const other = viewer === "client" ? booking.partner : booking.client;
  const terms = booking.cancellation_terms;

  async function act(action: BookingAction) {
    setPending(true);
    setError(undefined);
    const { error } = await runBookingAction(booking.id, action);
    setPending(false);
    if (error) {
      setError(bookingErrorMessage(error));
      return;
    }
    setConfirmingCancel(false);
    router.refresh();
  }

  return (
    <li className="flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-4 sm:p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar src={other.avatar_url} name={other.full_name} size={44} />
          <div>
            <p className="font-medium text-zinc-900 dark:text-zinc-50">
              {viewer === "client" ? "With " : ""}
              {other.full_name}
              {other.ntrp_rating && <span className="ml-1.5 text-sm font-normal text-zinc-500">NTRP {formatNtrp(other.ntrp_rating)}</span>}
            </p>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              {formatSession(booking.starts_at, booking.ends_at, booking.timezone)}
            </p>
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_TONES[booking.status]}`}>
          {STATUS_LABELS[booking.status]}
        </span>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        <a href={mapsLink(booking.club.lat, booking.club.lon)} target="_blank" rel="noopener noreferrer" className="font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          {booking.club.name} ↗
        </a>
        {booking.club.address && ` · ${booking.club.address}`}
      </p>
      {viewer === "client" && booking.paid_cents > 0 && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Paid {formatMoney(booking.paid_cents, booking.currency)}
          {booking.refunded_cents > 0 && ` · Refunded ${formatMoney(booking.refunded_cents, booking.currency)}`}
        </p>
      )}
      {booking.note && <p className="rounded-lg bg-zinc-50 px-3 py-2 text-sm text-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">“{booking.note}”</p>}
      {booking.cancellation_reason && <p className="text-sm text-zinc-500">Reason: {booking.cancellation_reason}</p>}
      {booking.status === "cancelled_late" && viewer === "client" && (
        <p className="text-sm text-red-700 dark:text-red-400">A {Math.round((booking.cancellation_fee_fraction ?? 0) * 100)}% late-cancellation fee applies.</p>
      )}
      {booking.credit_issued && viewer === "client" && (
        <p className="text-sm text-sky-700 dark:text-sky-400">
          {formatMoney(booking.paid_cents, booking.currency)} credited to your account for rebooking within 30 days.
        </p>
      )}

      {booking.actions.length > 0 && (
        <div className="flex flex-col gap-2">
          {confirmingCancel ? (
            <div className="flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900/60 dark:bg-amber-950/30">
              <p className="text-amber-900 dark:text-amber-200">
                {viewer === "partner"
                  ? "Cancel this session? The client won't be charged."
                  : terms && terms.fee_fraction_if_cancelled_now > 0
                    ? `It's less than 12 hours to go — cancelling now costs ${Math.round(terms.fee_fraction_if_cancelled_now * 100)}% of the session fee.`
                    : "Cancel this session? You won't be charged."}
              </p>
              <div className="flex gap-2">
                <Button type="button" variant="secondary" onClick={() => act("cancel")} disabled={pending}>
                  Yes, cancel
                </Button>
                <Button type="button" variant="ghost" onClick={() => setConfirmingCancel(false)}>
                  Keep it
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {booking.status === "held" && (
                <span className="text-sm text-amber-800 dark:text-amber-300">Awaiting payment — released automatically if unpaid.</span>
              )}
              {booking.actions.includes("complete") && (
                <Button type="button" onClick={() => act("complete")} disabled={pending}>
                  Mark completed
                </Button>
              )}
              {booking.actions.includes("no_show") && (
                <Button type="button" variant="secondary" onClick={() => act("no_show")} disabled={pending}>
                  Client didn&apos;t show
                </Button>
              )}
              {booking.actions.includes("cancel") && (
                <Button type="button" variant="ghost" onClick={() => setConfirmingCancel(true)} disabled={pending}>
                  Cancel session
                </Button>
              )}
              {booking.actions.includes("cancel") && terms && viewer === "client" && terms.fee_fraction_if_cancelled_now === 0 && (
                <span className="text-xs text-zinc-500">Free cancellation until {formatMoment(terms.free_until, booking.timezone)}</span>
              )}
            </div>
          )}
          {error && <Alert tone="error">{error}</Alert>}
        </div>
      )}
    </li>
  );
}
