import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { AvailabilityEditor } from "@/components/availability/availability-editor";
import { authedApi, requireUser } from "@/lib/auth/server";

export const metadata = { title: "Availability · Tennis Hitting Partner" };

export default async function AvailabilityPage() {
  const user = await requireUser("/availability");
  if (user.role !== "partner") redirect("/dashboard");
  const api = await authedApi();
  const { data: availability } = await api.GET("/me/availability");
  if (!availability) redirect("/onboarding/profile");
  const { data: preview } = availability.timezone
    ? await api.GET("/me/availability/preview", { params: { query: { days: 7 } } })
    : { data: undefined };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Availability</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Set when you can play. Clients see open times at the clubs you&apos;ve chosen.
          </p>
        </div>
        <AvailabilityEditor initial={availability} initialPreview={preview ?? null} />
      </main>
    </div>
  );
}
