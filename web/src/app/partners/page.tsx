import { AppHeader } from "@/components/app-header";
import { PartnerSearch, type SearchOrigin, type SearchView } from "@/components/partners/partner-search";
import { authedApi, requireUser } from "@/lib/auth/server";

export const metadata = { title: "Find a hitting partner · Tennis Hitting Partner" };

export default async function PartnersPage(props: PageProps<"/partners">) {
  const { view } = await props.searchParams;
  const user = await requireUser("/partners");
  const api = await authedApi();

  let origin: SearchOrigin | null = null;
  let myCourts: { id: string; name: string }[] | null = null;
  if (user.role === "client") {
    const [{ data }, { data: mine }] = await Promise.all([api.GET("/me/client-profile"), api.GET("/me/clubs")]);
    myCourts = (mine?.clubs ?? []).map(({ id, name }) => ({ id, name }));
    if (data)
      origin = {
        city: data.city,
        region: data.region ?? "",
        postal_code: data.postal_code ?? "",
        country_code: data.country_code,
        level: data.ntrp_rating,
      };
  } else if (user.role === "partner") {
    const { data } = await api.GET("/me/partner-profile");
    if (data)
      origin = {
        city: data.city,
        region: data.region ?? "",
        postal_code: data.postal_code ?? "",
        country_code: data.country_code,
        level: null,
      };
  }

  // Players with saved courts start with suggestions at them; ?view= picks a tab.
  const initialView: SearchView = view === "area" ? "area" : view === "courts" || myCourts?.length ? "courts" : "area";

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Find a hitting partner</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Verified partners at or above your level, at your courts or near you.
          </p>
        </div>
        <PartnerSearch
          origin={origin}
          myCourts={myCourts}
          initialView={initialView}
        />
      </main>
    </div>
  );
}
