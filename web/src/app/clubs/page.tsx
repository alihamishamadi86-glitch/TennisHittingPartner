import { AppHeader } from "@/components/app-header";
import { ClubFinder, type Location } from "@/components/clubs/club-finder";
import { authedApi, requireUser } from "@/lib/auth/server";
import type { MapTiles } from "@/lib/clubs/types";

export const metadata = { title: "Find courts · Tennis Hitting Partner" };

/** Tile server is runtime config so production can switch providers without a rebuild. */
function mapTiles(): MapTiles {
  return {
    url: process.env.MAP_TILE_URL ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      process.env.MAP_TILE_ATTRIBUTION ??
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  };
}

export default async function ClubsPage() {
  const user = await requireUser("/clubs");
  const api = await authedApi();

  let location: Location | null = null;
  let partnerClubIds: string[] | undefined;
  if (user.role === "client") {
    const { data } = await api.GET("/me/client-profile");
    if (data) location = { city: data.city, region: data.region ?? "", country_code: data.country_code };
  } else if (user.role === "partner") {
    const [{ data: profile }, { data: picks }] = await Promise.all([api.GET("/me/partner-profile"), api.GET("/me/partner-clubs")]);
    if (profile) location = { city: profile.city, region: profile.region ?? "", country_code: profile.country_code };
    partnerClubIds = picks?.club_ids ?? [];
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
              : "Tennis clubs, centres and public courts in your city."}
          </p>
        </div>
        <ClubFinder initialLocation={location} tiles={mapTiles()} partnerClubIds={partnerClubIds} />
      </main>
    </div>
  );
}
