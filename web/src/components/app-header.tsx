import Link from "next/link";

import { LogoutButton } from "@/components/auth/logout-button";
import { Avatar } from "@/components/ui/avatar";
import { Logo } from "@/components/ui/logo";
import type { User } from "@/lib/auth/types";

export function AppHeader({ user }: { user: User }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-zinc-200 bg-white px-4 py-3 sm:px-8 dark:border-zinc-800 dark:bg-zinc-900">
      <Logo />
      <nav className="flex items-center gap-1 sm:gap-3">
        {user.role === "admin" && (
          <Link href="/admin/partners" className="rounded-lg px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800">
            Partner queue
          </Link>
        )}
        <span className="hidden items-center gap-2 text-sm text-zinc-600 sm:flex dark:text-zinc-400">
          <Avatar src={user.avatar_url} name={user.full_name || user.email} size={28} />
          {user.email}
        </span>
        <LogoutButton />
      </nav>
    </header>
  );
}
