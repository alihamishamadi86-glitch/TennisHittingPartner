import { notFound } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { NotificationSettings } from "@/components/settings/notification-settings";
import { authedApi, requireUser } from "@/lib/auth/server";

export const metadata = { title: "Settings · Tennis Hitting Partner" };

export default async function SettingsPage() {
  const user = await requireUser("/settings");
  const { data } = await (await authedApi()).GET("/me/notifications");
  if (!data) notFound();
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8 sm:px-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Notifications</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">How we remind you about your sessions.</p>
        </div>
        <NotificationSettings initial={data} />
      </main>
    </div>
  );
}
