"use client";

import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

// One Stripe.js instance per publishable key for the page's lifetime.
const stripeByKey = new Map<string, Promise<Stripe | null>>();
function stripeFor(key: string) {
  if (!stripeByKey.has(key)) stripeByKey.set(key, loadStripe(key));
  return stripeByKey.get(key)!;
}

function PayForm({ label, onPaid }: { label: string; onPaid: () => void }) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!stripe || !elements) return;
    setPending(true);
    setError(undefined);
    // No redirect for cards; 3-D Secure opens in a modal. Confirmation comes from our webhook.
    const result = await stripe.confirmPayment({ elements, redirect: "if_required" });
    if (result.error) {
      setError(result.error.message ?? "Payment failed.");
      setPending(false);
      return;
    }
    onPaid();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <PaymentElement options={{ layout: "tabs" }} />
      {error && <Alert tone="error">{error}</Alert>}
      <Button type="submit" disabled={!stripe || pending}>
        {pending ? "Processing…" : label}
      </Button>
    </form>
  );
}

export function StripePayment({
  publishableKey,
  clientSecret,
  label,
  onPaid,
}: {
  publishableKey: string;
  clientSecret: string;
  label: string;
  onPaid: () => void;
}) {
  return (
    <Elements
      key={clientSecret}
      stripe={stripeFor(publishableKey)}
      options={{ clientSecret, appearance: { theme: "stripe", variables: { colorPrimary: "#059669" } } }}
    >
      <PayForm label={label} onPaid={onPaid} />
    </Elements>
  );
}
