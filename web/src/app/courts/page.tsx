import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { MyCourts } from "@/components/clubs/my-courts";
import { authedApi, requireUser } from "@/lib/auth/server";
import { mapTiles } from "@/lib/clubs/tiles";

export const metadata = { title: "My courts · Tennis Hitting Partner" };

export default async function MyCourtsPage() {
  const user = await requireUser("/courts");
  if (user.role !== "client" && user.role !== "partner") redirect("/clubs");
  const api = await authedApi();
  const { data } = await api.GET("/me/clubs");

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">My courts</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {user.role === "partner"
              ? "The places you play at. Clients book you at these courts, and players who list them see you first."
              : "The places you like to play. We suggest hitting partners who play at these courts or close by."}
          </p>
        </div>
        <MyCourts role={user.role} initialClubs={data?.clubs ?? []} tiles={mapTiles()} />
      </main>
    </div>
  );
}
