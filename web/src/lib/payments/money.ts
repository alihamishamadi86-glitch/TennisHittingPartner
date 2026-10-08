import type { components } from "@/lib/api/schema";

export type PaymentsConfig = components["schemas"]["PaymentsConfigOut"];
export type Checkout = components["schemas"]["CheckoutOut"];
export type Payment = components["schemas"]["PaymentOut"];
export type Credits = components["schemas"]["CreditsOut"];

export function formatMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}
