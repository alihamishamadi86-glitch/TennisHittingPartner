"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { bookingErrorMessage } from "@/lib/bookings/actions";
import type { Booking } from "@/lib/bookings/types";
import { formatMoney, type Checkout, type PaymentsConfig } from "@/lib/payments/money";

import { StripePayment } from "./stripe-payment";

const CONFIRM_POLL_MS = 1500;
const CONFIRM_TIMEOUT_MS = 30_000;

/** Prices the held booking (promo → credit → card) and takes payment. */
export function CheckoutPanel({
  booking,
  config,
  onConfirmed,
}: {
  booking: Booking;
  config: PaymentsConfig;
  onConfirmed: (booking: Booking) => void;
}) {
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [promo, setPromo] = useState("");
  const [error, setError] = useState<string>();
  const [state, setState] = useState<"pricing" | "ready" | "confirming">("pricing");

  const start = useCallback(
    async (code: string | null) => {
      setState("pricing");
      setError(undefined);
      const { data, error } = await apiBrowser.POST("/bookings/{booking_id}/checkout", {
        params: { path: { booking_id: booking.id } },
        body: { promo_code: code },
      });
      if (!data) {
        setError(bookingErrorMessage(error));
        setState("ready");
        return false;
      }
      setCheckout(data);
      if (data.booking.status === "confirmed") onConfirmed(data.booking); // fully covered by credit
      setState("ready");
      return true;
    },
    [booking.id, onConfirmed],
  );

  useEffect(() => {
    const timer = setTimeout(() => void start(null), 0);
    return () => clearTimeout(timer);
  }, [start]);

  // The webhook confirms the booking; wait for it rather than trusting the browser.
  async function awaitConfirmation() {
    setState("confirming");
    const started = Date.now();
    while (Date.now() - started < CONFIRM_TIMEOUT_MS) {
      const { data } = await apiBrowser.GET("/bookings/{booking_id}", { params: { path: { booking_id: booking.id } } });
      if (data && data.status !== "held") {
        onConfirmed(data);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, CONFIRM_POLL_MS));
    }
    setError("Payment received — confirmation is taking longer than usual. Check My sessions in a minute.");
    setState("ready");
  }

  async function simulatePayment() {
    if (!checkout) return;
    setState("confirming");
    // Dev-only route (fake gateway), deliberately absent from the public API schema.
    await fetch(`/api/dev-payments/${checkout.payment.id}/succeed`, { method: "POST" });
    await awaitConfirmation();
  }

  async function applyPromo(event: FormEvent) {
    event.preventDefault();
    if (promo.trim()) await start(promo.trim());
  }

  const payment = checkout?.payment;
  const money = (cents: number) => formatMoney(cents, payment?.currency ?? config.currency);

  return (
    <div className="flex flex-col gap-4">
      {payment && (
        <dl className="flex flex-col gap-1.5 rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
          <div className="flex justify-between">
            <dt className="text-zinc-600 dark:text-zinc-400">{booking.duration_minutes}-minute session</dt>
            <dd className="tabular-nums">{money(payment.price_cents)}</dd>
          </div>
          {payment.discount_cents > 0 && (
            <div className="flex justify-between text-emerald-700 dark:text-emerald-400">
              <dt>Promo code</dt>
              <dd className="tabular-nums">−{money(payment.discount_cents)}</dd>
            </div>
          )}
          {payment.credit_applied_cents > 0 && (
            <div className="flex justify-between text-emerald-700 dark:text-emerald-400">
              <dt>Account credit</dt>
              <dd className="tabular-nums">−{money(payment.credit_applied_cents)}</dd>
            </div>
          )}
          <div className="mt-1 flex justify-between border-t border-zinc-200 pt-2 font-semibold dark:border-zinc-800">
            <dt>Total</dt>
            <dd className="tabular-nums">{money(payment.amount_cents)}</dd>
          </div>
        </dl>
      )}

      <form onSubmit={applyPromo} className="flex gap-2">
        <input
          aria-label="Promo code"
          placeholder="Promo code"
          value={promo}
          onChange={(e) => setPromo(e.target.value)}
          className="h-10 flex-1 rounded-lg border border-zinc-300 bg-white px-3 text-sm uppercase outline-none focus:border-emerald-600 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <Button type="submit" variant="secondary" disabled={state !== "ready" || !promo.trim()}>
          Apply
        </Button>
      </form>

      {error && <Alert tone="error">{error}</Alert>}
      {state === "pricing" && <p className="text-sm text-zinc-500">Preparing payment…</p>}
      {state === "confirming" && <Alert>Confirming your payment…</Alert>}

      {state === "ready" && payment && checkout?.client_secret && (
        config.provider === "stripe" && config.publishable_key ? (
          <StripePayment
            publishableKey={config.publishable_key}
            clientSecret={checkout.client_secret}
            label={`Pay ${money(payment.amount_cents)}`}
            onPaid={awaitConfirmation}
          />
        ) : (
          <div className="flex flex-col gap-3 rounded-lg border border-dashed border-amber-400 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950/30">
            <p className="text-sm text-amber-900 dark:text-amber-200">
              <strong>Development mode:</strong> payments are simulated. Configure Stripe test keys to take real card
              payments.
            </p>
            <Button type="button" onClick={simulatePayment}>
              Pay {money(payment.amount_cents)} (simulated)
            </Button>
          </div>
        )
      )}
    </div>
  );
}
