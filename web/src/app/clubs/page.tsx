import { AppHeader } from "@/components/app-header";
import { ClubFinder, type Location } from "@/components/clubs/club-finder";
import { authedApi, requireUser } from "@/lib/auth/server";
import { mapTiles } from "@/lib/clubs/tiles";

export const metadata = { title: "Find courts · Tennis Hitting Partner" };

export default async function ClubsPage() {
  const user = await requireUser("/clubs");
  const api = await authedApi();

  let location: Location | null = null;
  let myClubIds: string[] | undefined;
  if (user.role === "client" || user.role === "partner") {
    const [{ data: profile }, { data: mine }] = await Promise.all([
      user.role === "client" ? api.GET("/me/client-profile") : api.GET("/me/partner-profile"),
      api.GET("/me/clubs"),
    ]);
    if (profile)
      location = { city: profile.city, region: profile.region ?? "", postal_code: profile.postal_code ?? "", country_code: profile.country_code };
    myClubIds = mine?.club_ids ?? [];
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            {user.role === "partner" ? "Where you play" : "Courts near you"}
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {user.role === "partner"
              ? "Choose the clubs and public courts you're happy to play at. Clients book you at these places."
              : "Tennis clubs, centres and public courts in your city. Tick the ones you play at and we'll suggest partners who play there too."}
          </p>
        </div>
        <ClubFinder initialLocation={location} tiles={mapTiles()} myClubIds={myClubIds} />
      </main>
    </div>
  );
}
