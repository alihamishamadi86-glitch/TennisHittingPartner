"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ResendVerification } from "@/components/auth/resend-verification";
import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Button, buttonClasses } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiBrowser } from "@/lib/api/browser";
import { bookingErrorMessage, runBookingAction } from "@/lib/bookings/actions";
import type { PartnerPublic } from "@/lib/availability/format";
import { formatSession, type Booking, type Waiver } from "@/lib/bookings/types";
import { formatNtrp } from "@/lib/profile/labels";

import { CheckoutPanel } from "@/components/payments/checkout-panel";
import { formatMoney, type PaymentsConfig } from "@/lib/payments/money";

import { WaiverForm } from "./waiver-form";

const message = bookingErrorMessage;

function useCountdown(until: string | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [until]);
  return until ? Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000)) : 0;
}

export function BookingFlow({
  partner,
  startsAt,
  duration,
  waiver,
  emailVerified,
  userName,
  paymentsConfig,
  myClubIds,
}: {
  partner: PartnerPublic;
  startsAt: string;
  duration: number;
  waiver: Waiver | null;
  emailVerified: boolean;
  userName: string;
  paymentsConfig: PaymentsConfig;
  /** The player's saved courts: one the partner also plays at is picked by default. */
  myClubIds: string[];
}) {
  const [clubId, setClubId] = useState(
    (partner.clubs.find((club) => myClubIds.includes(club.id)) ?? partner.clubs[0])?.id ?? "",
  );
  const [note, setNote] = useState("");
  const [waiverSigned, setWaiverSigned] = useState(!waiver || waiver.signed);
  const [booking, setBooking] = useState<Booking | null>(null);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const secondsLeft = useCountdown(booking?.status === "held" ? booking.hold_expires_at : null);
  const timeZone = partner.timezone ?? "UTC";
  const endsAt = new Date(new Date(startsAt).getTime() + duration * 60_000).toISOString();

  async function reserve() {
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/bookings", {
      body: { partner_id: partner.user_id, club_id: clubId, starts_at: startsAt, duration_minutes: duration, note },
    });
    setPending(false);
    if (data) setBooking(data);
    else setError(message(error));
  }

  async function act(action: "cancel") {
    if (!booking) return;
    setPending(true);
    setError(undefined);
    const { data, error } = await runBookingAction(booking.id, action, "Released before confirming");
    setPending(false);
    if (data) setBooking(data);
    else setError(message(error));
  }

  const summary = (
    <div className="flex items-center gap-4">
      <Avatar src={partner.avatar_url} name={partner.full_name} size={56} />
      <div className="flex flex-col gap-0.5">
        <p className="font-semibold text-zinc-900 dark:text-zinc-50">
          {partner.full_name}
          {partner.ntrp_rating && (
            <span className="ml-2 text-sm font-normal text-zinc-500">NTRP {formatNtrp(partner.ntrp_rating)}</span>
          )}
        </p>
        <p className="text-sm text-zinc-700 dark:text-zinc-300">{formatSession(startsAt, endsAt, timeZone)}</p>
        <p className="text-xs text-zinc-500">Times shown in {timeZone.replace(/_/g, " ")}</p>
      </div>
    </div>
  );

  if (booking?.status === "confirmed") {
    return (
      <div className="flex flex-col gap-5">
        {summary}
        <Alert tone="success">
          You&apos;re booked at <strong>{booking.club.name}</strong>. We&apos;ve emailed you and {partner.full_name} the details.
        </Alert>
        <Link href="/sessions" className={buttonClasses("primary", "w-fit")}>
          View my sessions
        </Link>
      </div>
    );
  }

  if (booking && booking.status !== "held") {
    return (
      <div className="flex flex-col gap-5">
        {summary}
        <Alert>
          {booking.status === "expired" ? "Your hold expired." : "Hold released."} This time may still be available.
        </Alert>
        <Link href={`/partners/${partner.user_id}?duration=${duration}`} className={buttonClasses("secondary", "w-fit")}>
          Choose a time
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {summary}

      {!emailVerified && (
        <Alert>
          Confirm your email address before booking. <ResendVerification />
        </Alert>
      )}

      {!waiverSigned && waiver ? (
        <WaiverForm waiver={waiver} expectedName={userName} onSigned={() => setWaiverSigned(true)} />
      ) : booking ? (
        <div className="flex flex-col gap-4">
          <Alert>
            Held for you for{" "}
            <strong className="tabular-nums">
              {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}
            </strong>{" "}
            at <strong>{booking.club.name}</strong>. Free cancellation until{" "}
            {booking.cancellation_terms &&
              new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone }).format(
                new Date(booking.cancellation_terms.free_until),
              )}
            ; 50% fee after that.
          </Alert>
          {secondsLeft > 0 ? (
            <CheckoutPanel booking={booking} config={paymentsConfig} onConfirmed={setBooking} />
          ) : (
            <Alert tone="error">This hold has expired.</Alert>
          )}
          <Button type="button" variant="ghost" onClick={() => act("cancel")} disabled={pending} className="w-fit">
            Release this time
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium text-zinc-800 dark:text-zinc-200">Where</legend>
            {partner.clubs.map((club) => (
              <label key={club.id} className="flex cursor-pointer items-center gap-2.5 text-sm text-zinc-800 dark:text-zinc-200">
                <input
                  type="radio"
                  name="club"
                  checked={clubId === club.id}
                  onChange={() => setClubId(club.id)}
                  className="h-4 w-4 accent-emerald-600"
                />
                {club.name}
                {myClubIds.includes(club.id) && <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">Your court</span>}
              </label>
            ))}
          </fieldset>
          <p className="text-xs text-zinc-500">
            You arrange court access at the venue (public courts are first come, first served). Your partner brings a basket of
            balls.
          </p>
          <Textarea
            id="note"
            label="Note for your partner (optional)"
            rows={3}
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What would you like to work on?"
          />
          <Button type="button" onClick={reserve} disabled={pending || !clubId || !emailVerified} className="w-fit">
            {pending
              ? "Reserving…"
              : `Reserve · ${formatMoney(paymentsConfig.prices_cents[duration] ?? 0, paymentsConfig.currency)}`}
          </Button>
        </div>
      )}

      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}
