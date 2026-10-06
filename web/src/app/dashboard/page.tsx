import { redirect } from "next/navigation";

import { LogoutButton } from "@/components/auth/logout-button";
import { ResendVerification } from "@/components/auth/resend-verification";
import { Alert } from "@/components/ui/alert";
import { Logo } from "@/components/ui/logo";
import { requireUser } from "@/lib/auth/server";

export const metadata = { title: "Dashboard · Tennis Hitting Partner" };

const NEXT_STEPS = {
  client: [
    { title: "Complete your player profile", body: "Share your level (NTRP) and goals so we can match you." },
    { title: "Find courts near you", body: "We'll list tennis clubs and public courts in your city." },
    { title: "Book a hitting partner", body: "Pick a partner and an open slot that suits you." },
  ],
  partner: [
    { title: "Complete your partner profile", body: "Your playing background, level and a photo." },
    { title: "Get verified", body: "We'll confirm your level with a short court screening." },
    { title: "Set your availability", body: "Choose the clubs and times you can play." },
  ],
  admin: [{ title: "Admin tools", body: "Partner verification arrives in the next milestone." }],
} as const;

export default async function DashboardPage() {
  const user = await requireUser("/dashboard");
  if (!user.role) redirect("/onboarding/role");

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="flex items-center justify-between gap-4 border-b border-zinc-200 bg-white px-4 py-3 sm:px-8 dark:border-zinc-800 dark:bg-zinc-900">
        <Logo />
        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-zinc-600 sm:inline dark:text-zinc-400">{user.email}</span>
          <LogoutButton />
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-10 sm:px-8">
        {!user.email_verified && (
          <Alert>
            Confirm your email address — we sent a link to <strong>{user.email}</strong>.{" "}
            <ResendVerification />
          </Alert>
        )}
        <div className="flex flex-col gap-2">
          <span className="w-fit rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            {user.role === "partner" ? "Hitting partner" : user.role === "admin" ? "Admin" : "Player"}
          </span>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Hi {user.full_name.split(" ")[0] || "there"}
          </h1>
        </div>
        <ol className="grid gap-3">
          {NEXT_STEPS[user.role].map((step, index) => (
            <li
              key={step.title}
              className="flex gap-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-zinc-100 text-sm font-semibold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                {index + 1}
              </span>
              <div>
                <p className="font-medium text-zinc-900 dark:text-zinc-50">{step.title}</p>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </main>
    </div>
  );
}
