import type { ReactNode } from "react";

import { AppHeader } from "@/components/app-header";
import { requireUser } from "@/lib/auth/server";
import { notFound } from "next/navigation";

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const user = await requireUser("/admin/partners");
  if (user.role !== "admin") notFound();
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8">{children}</main>
    </div>
  );
}
