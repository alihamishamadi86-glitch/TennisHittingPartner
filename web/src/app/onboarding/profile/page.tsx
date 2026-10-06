import { redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ClientProfileForm } from "@/components/profile/client-profile-form";
import { PartnerProfileForm } from "@/components/profile/partner-profile-form";
import { authedApi, requireUser } from "@/lib/auth/server";

export const metadata = { title: "Your profile · Tennis Hitting Partner" };

export default async function ProfilePage() {
  const user = await requireUser("/onboarding/profile");
  if (!user.role) redirect("/onboarding/role");
  if (user.role === "admin") redirect("/admin/partners");

  const api = await authedApi();
  const form =
    user.role === "client" ? (
      <ClientProfileForm initial={(await api.GET("/me/client-profile")).data ?? null} />
    ) : (
      <PartnerProfileForm
        initial={(await api.GET("/me/partner-profile")).data ?? null}
        name={user.full_name || user.email}
        avatarUrl={user.avatar_url}
      />
    );

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-2xl px-4 py-8 sm:py-12">
        <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900">
          {form}
        </div>
      </main>
    </div>
  );
}
