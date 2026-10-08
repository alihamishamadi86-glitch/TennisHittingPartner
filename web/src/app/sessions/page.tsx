import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { SessionCard } from "@/components/bookings/session-card";
import { Alert } from "@/components/ui/alert";
import { buttonClasses } from "@/components/ui/button";
import { authedApi, requireUser } from "@/lib/auth/server";
import { formatMoney } from "@/lib/payments/money";

export const metadata = { title: "My sessions · Tennis Hitting Partner" };

export default async function SessionsPage(props: PageProps<"/sessions">) {
  const user = await requireUser("/sessions");
  if (user.role !== "client" && user.role !== "partner") redirect("/dashboard");
  const { scope: scopeParam } = await props.searchParams;
  const scope = scopeParam === "past" ? "past" : "upcoming";
  const api = await authedApi();
  const [{ data: bookings = [] }, { data: credits }] = await Promise.all([
    api.GET("/bookings", { params: { query: { scope } } }),
    user.role === "client" ? api.GET("/me/credits") : Promise.resolve({ data: undefined }),
  ]);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 sm:px-8">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">My sessions</h1>
        {credits && credits.balance_cents > 0 && (
          <Alert tone="success">
            You have {formatMoney(credits.balance_cents, credits.currency)} in credit — it&apos;s applied automatically
            at checkout.
          </Alert>
        )}
        <nav className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800" aria-label="Sessions">
          {(["upcoming", "past"] as const).map((tab) => (
            <Link
              key={tab}
              href={`/sessions?scope=${tab}`}
              aria-current={tab === scope ? "page" : undefined}
              className={`border-b-2 px-3 py-2 text-sm font-medium capitalize ${
                tab === scope ? "border-emerald-600 text-zinc-900 dark:text-zinc-50" : "border-transparent text-zinc-500 hover:text-zinc-800"
              }`}
            >
              {tab}
            </Link>
          ))}
        </nav>
        {bookings.length === 0 ? (
          <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-zinc-300 p-8 dark:border-zinc-700">
            <p className="text-sm text-zinc-500">{scope === "upcoming" ? "No upcoming sessions." : "No past sessions yet."}</p>
            {user.role === "client" && scope === "upcoming" && (
              <Link href="/partners" className={buttonClasses("primary")}>
                Find a hitting partner
              </Link>
            )}
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {bookings.map((b) => (
              <SessionCard key={b.id} booking={b} viewer={user.role as "client" | "partner"} />
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
