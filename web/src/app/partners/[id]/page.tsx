import Link from "next/link";
import { notFound } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { SlotPreview } from "@/components/availability/slot-preview";
import { Avatar } from "@/components/ui/avatar";
import { authedApi, requireUser } from "@/lib/auth/server";
import { zoneLabel } from "@/lib/availability/format";
import { formatMoney } from "@/lib/payments/money";
import { BACKGROUND_LABELS, HAND_LABELS, STYLE_LABELS, formatNtrp } from "@/lib/profile/labels";

export const metadata = { title: "Hitting partner · Tennis Hitting Partner" };

export default async function PartnerPage(props: PageProps<"/partners/[id]">) {
  const { id } = await props.params;
  const { duration: durationParam } = await props.searchParams;
  const duration = durationParam === "90" ? 90 : 60;
  const user = await requireUser(`/partners/${id}`);
  const api = await authedApi();
  const [{ data: partner }, { data: slots }, { data: paymentsConfig }, myClubIds] = await Promise.all([
    api.GET("/partners/{partner_id}", { params: { path: { partner_id: id } } }),
    api.GET("/partners/{partner_id}/slots", { params: { path: { partner_id: id }, query: { days: 7, duration } } }),
    api.GET("/payments/config"),
    user.role === "client" ? api.GET("/me/clubs").then((r) => r.data?.club_ids ?? []) : Promise.resolve<string[]>([]),
  ]);
  if (!partner) notFound();

  const facts: [string, string | null][] = [
    ["Level", partner.ntrp_rating ? `NTRP ${formatNtrp(partner.ntrp_rating)} (verified)` : null],
    ["Background", partner.background ? BACKGROUND_LABELS[partner.background] : null],
    ["Style", partner.play_style ? STYLE_LABELS[partner.play_style] : null],
    ["Plays", partner.dominant_hand ? HAND_LABELS[partner.dominant_hand as keyof typeof HAND_LABELS] : null],
    ["Experience", partner.years_playing ? `${partner.years_playing} years` : null],
  ];

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-8 sm:px-8">
        <Link href="/partners" className="w-fit text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          ← All partners
        </Link>
        <div className="flex flex-wrap items-center gap-4">
          <Avatar src={partner.avatar_url} name={partner.full_name} size={88} />
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{partner.full_name}</h1>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {partner.city}
              {partner.region ? `, ${partner.region}` : ""}
            </p>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              {facts
                .filter(([, v]) => v)
                .map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-zinc-500">{label}</dt>
                    <dd className="font-medium text-zinc-900 dark:text-zinc-100">{value}</dd>
                  </div>
                ))}
            </dl>
            {partner.bio && <p className="whitespace-pre-line text-sm text-zinc-800 dark:text-zinc-200">{partner.bio}</p>}
            <div>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-zinc-500">Plays at</h2>
              <ul className="flex flex-col gap-1 text-sm text-zinc-800 dark:text-zinc-200">
                {partner.clubs.map((c) => (
                  <li key={c.id}>
                    {c.name}
                    {myClubIds.includes(c.id) && (
                      <span className="ml-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">Your court</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Open times</h2>
              <div className="flex gap-1.5 text-sm">
                {[60, 90].map((m) => (
                  <Link
                    key={m}
                    href={`/partners/${id}?duration=${m}`}
                    className={`rounded-full border px-3 py-1 font-medium ${
                      duration === m ? "border-emerald-600 bg-emerald-600 text-white" : "border-zinc-300 dark:border-zinc-700"
                    }`}
                  >
                    {m} min
                    {paymentsConfig?.prices_cents[m] !== undefined &&
                      ` · ${formatMoney(paymentsConfig.prices_cents[m], paymentsConfig.currency)}`}
                  </Link>
                ))}
              </div>
            </div>
            {slots ? (
              <>
                <p className="text-xs text-zinc-500">Times in {zoneLabel(slots.timezone)} ({slots.timezone.replace(/_/g, " ")}).</p>
                <SlotPreview
                  slots={slots}
                  emptyText="No open times this week."
                  bookingHref={
                    user.role === "client"
                      ? (slot) => `/book?partner=${id}&start=${encodeURIComponent(slot)}&duration=${duration}`
                      : undefined
                  }
                />
              </>
            ) : (
              <p className="text-sm text-zinc-500">This partner hasn&apos;t published availability yet.</p>
            )}
            {user.role === "client" && <p className="text-xs text-zinc-500">Pick a time to book. Free cancellation up to 12 hours before.</p>}
          </section>
        </div>
      </main>
    </div>
  );
}
