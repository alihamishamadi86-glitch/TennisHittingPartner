import { headers } from "next/headers";
import Link from "next/link";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/app-header";
import { SwitchAccountButton } from "@/components/auth/switch-account-button";
import { buttonClasses } from "@/components/ui/button";
import { PATH_HEADER } from "@/lib/auth/path-header";
import { safeNextPath } from "@/lib/auth/redirect";
import { requireUser } from "@/lib/auth/server";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const path = safeNextPath((await headers()).get(PATH_HEADER) ?? undefined, "/admin/partners");
  const user = await requireUser(path);

  if (user.role !== "admin") {
    // Common when following an admin email link in a browser signed in as someone else
    // (e.g. the partner who just applied): explain and offer to switch, rather than 404.
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
        <AppHeader user={user} />
        <main className="mx-auto flex w-full max-w-lg flex-col gap-4 px-4 py-16">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Admins only</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            You&apos;re signed in as <strong className="text-zinc-900 dark:text-zinc-100">{user.email}</strong>, which
            isn&apos;t an admin account. Switch to an admin account to open this page.
          </p>
          <div className="flex gap-2">
            <SwitchAccountButton returnTo={path} />
            <Link href="/dashboard" className={buttonClasses("ghost")}>
              Back to dashboard
            </Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8">{children}</main>
    </div>
  );
}
