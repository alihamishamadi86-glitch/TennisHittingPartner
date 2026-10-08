import { notFound, redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { BookingFlow } from "@/components/bookings/booking-flow";
import { authedApi, requireUser } from "@/lib/auth/server";

export const metadata = { title: "Book a session · Tennis Hitting Partner" };

export default async function BookPage(props: PageProps<"/book">) {
  const params = await props.searchParams;
  const partnerId = typeof params.partner === "string" ? params.partner : null;
  const start = typeof params.start === "string" ? params.start : null;
  const duration = params.duration === "90" ? 90 : 60;
  if (!partnerId || !start || Number.isNaN(Date.parse(start))) notFound();

  const returnTo = `/book?partner=${partnerId}&start=${encodeURIComponent(start)}&duration=${duration}`;
  const user = await requireUser(returnTo);
  if (user.role !== "client") redirect(`/partners/${partnerId}`);
  if (!user.profile_complete) redirect("/onboarding/profile");

  const api = await authedApi();
  const [{ data: partner }, { data: waiver }, { data: paymentsConfig }] = await Promise.all([
    api.GET("/partners/{partner_id}", { params: { path: { partner_id: partnerId } } }),
    api.GET("/waiver"),
    api.GET("/payments/config"),
  ]);
  if (!partner || !paymentsConfig) notFound();

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-2xl px-4 py-8 sm:py-12">
        <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900">
          <h1 className="mb-6 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Book a session</h1>
          <BookingFlow
            partner={partner}
            startsAt={start}
            duration={duration}
            waiver={waiver ?? null}
            emailVerified={user.email_verified}
            userName={user.full_name}
            paymentsConfig={paymentsConfig}
          />
        </div>
      </main>
    </div>
  );
}
