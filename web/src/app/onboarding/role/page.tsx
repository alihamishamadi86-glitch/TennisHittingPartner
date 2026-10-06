import { redirect } from "next/navigation";

import { AuthHeading } from "@/components/auth/auth-heading";
import { RoleChooser } from "@/components/auth/role-chooser";
import { Logo } from "@/components/ui/logo";
import { requireUser } from "@/lib/auth/server";

export const metadata = { title: "Get started · Tennis Hitting Partner" };

export default async function ChooseRolePage() {
  const user = await requireUser("/onboarding/role");
  if (user.role) redirect("/dashboard");

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 dark:bg-zinc-950">
      <header className="px-4 py-5 sm:px-8">
        <Logo />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-6 sm:pt-12">
        <div className="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm sm:p-8 dark:border-zinc-800 dark:bg-zinc-900">
          <AuthHeading title={`Welcome${user.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`}>
            How will you use Tennis Hitting Partner? You can&apos;t change this later.
          </AuthHeading>
          <RoleChooser />
        </div>
      </main>
    </div>
  );
}
