import Link from "next/link";
import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ResendVerification } from "@/components/auth/resend-verification";
import { Alert } from "@/components/ui/alert";
import { buttonClasses } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { authedApi, requireUser } from "@/lib/auth/server";
import type { User } from "@/lib/auth/types";
import { formatNtrp } from "@/lib/profile/labels";
import type { PartnerProfile } from "@/lib/profile/types";

export const metadata = { title: "Dashboard · Tennis Hitting Partner" };

type StepItem = { title: string; body: string; done?: boolean; href?: string };

function clientSteps(user: User, courtCount: number): StepItem[] {
  return [
    {
      title: "Complete your player profile",
      body: "Share your level (NTRP) and goals so we can match you.",
      done: user.profile_complete,
      href: "/onboarding/profile",
    },
    {
      title: "Save your courts",
      body: courtCount
        ? `You play at ${courtCount} place${courtCount === 1 ? "" : "s"}.`
        : "Pick the clubs and public courts you play at.",
      done: courtCount > 0,
      href: courtCount ? "/courts" : "/clubs",
    },
    {
      title: "Find a hitting partner",
      body: courtCount
        ? "Verified partners at your level who play at your courts."
        : "Verified partners at your level with open times near you.",
      href: "/partners",
    },
  ];
}

function partnerSteps(
  user: User,
  profile: PartnerProfile | null,
  clubCount: number,
  hasSchedule: boolean,
): StepItem[] {
  const status = profile?.status ?? "draft";
  return [
    {
      title: "Complete your partner profile",
      body: "Your playing background, level, bio and a photo.",
      done: user.profile_complete,
      href: "/onboarding/profile",
    },
    {
      title: "Get verified",
      body: "We'll confirm your level with a short court screening.",
      done: status === "approved",
    },
    {
      title: "Choose your courts",
      body: clubCount ? `You play at ${clubCount} place${clubCount === 1 ? "" : "s"}.` : "Pick the clubs and courts you can play at.",
      done: clubCount > 0,
      href: clubCount ? "/courts" : "/clubs",
    },
    {
      title: "Set your availability",
      body: hasSchedule ? "Your weekly hours are set." : "Choose the times you can play.",
      done: hasSchedule,
      href: "/availability",
    },
  ];
}

export default async function DashboardPage() {
  const user = await requireUser("/dashboard");
  if (!user.role) redirect("/onboarding/role");

  const api = await authedApi();
  const hasCourts = user.role === "partner" || user.role === "client";
  const [partnerProfile, courtCount, hasSchedule] = await Promise.all([
    user.role === "partner" ? api.GET("/me/partner-profile").then((r) => r.data ?? null) : null,
    hasCourts ? api.GET("/me/clubs").then((r) => r.data?.club_ids.length ?? 0) : 0,
    user.role === "partner" ? api.GET("/me/availability").then((r) => (r.data?.windows.length ?? 0) > 0) : false,
  ]);
  const steps =
    user.role === "partner"
      ? partnerSteps(user, partnerProfile, courtCount, hasSchedule)
      : user.role === "client"
        ? clientSteps(user, courtCount)
        : [];

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-10 sm:px-8">
        {!user.email_verified && (
          <Alert>
            Confirm your email address — we sent a link to <strong>{user.email}</strong>. <ResendVerification />
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

        {user.role === "admin" && (
          <Link href="/admin/partners" className={buttonClasses("primary", "w-fit")}>
            Review partner applications
          </Link>
        )}

        {partnerProfile && partnerProfile.status !== "draft" && (
          <div className="flex flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium text-zinc-900 dark:text-zinc-50">Application status</p>
              <StatusBadge status={partnerProfile.status} />
            </div>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {partnerProfile.status === "applied" && "Thanks for applying! We'll be in touch to schedule a short court screening."}
              {partnerProfile.status === "screened" && "You passed screening — final approval is on its way."}
              {partnerProfile.status === "approved" &&
                `You're approved at NTRP ${formatNtrp(partnerProfile.verified_ntrp_rating ?? partnerProfile.ntrp_rating)}. Clients can find you once your clubs and hours are set.`}
              {partnerProfile.status === "rejected" && "Your application wasn't approved. Check your email for details, update your profile and resubmit."}
            </p>
          </div>
        )}

        <ol className="grid gap-3">
          {steps.map((step, index) => {
            const body = (
              <>
                <span
                  className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-sm font-semibold ${
                    step.done
                      ? "bg-emerald-600 text-white"
                      : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                  }`}
                >
                  {step.done ? "✓" : index + 1}
                </span>
                <div className="flex-1">
                  <p className="font-medium text-zinc-900 dark:text-zinc-50">{step.title}</p>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">{step.body}</p>
                </div>
                {step.href && (
                  <span className="self-center text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                    {step.done ? "Edit" : "Start"} →
                  </span>
                )}
              </>
            );
            const className = "flex gap-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900";
            return (
              <li key={step.title}>
                {step.href ? (
                  <Link href={step.href} className={`${className} transition-colors hover:border-emerald-600`}>
                    {body}
                  </Link>
                ) : (
                  <div className={className}>{body}</div>
                )}
              </li>
            );
          })}
        </ol>
      </main>
    </div>
  );
}
