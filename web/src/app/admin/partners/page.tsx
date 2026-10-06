import Link from "next/link";

import { Avatar } from "@/components/ui/avatar";
import { StatusBadge } from "@/components/ui/status-badge";
import { authedApi } from "@/lib/auth/server";
import { BACKGROUND_LABELS, STATUS_LABELS, formatNtrp } from "@/lib/profile/labels";
import type { PartnerStatus } from "@/lib/profile/types";

export const metadata = { title: "Partner applications · Admin" };

const TABS: (PartnerStatus | "all")[] = ["applied", "screened", "approved", "rejected", "all"];

export default async function PartnerQueuePage(props: PageProps<"/admin/partners">) {
  const { status } = await props.searchParams;
  const active = TABS.includes(status as PartnerStatus) ? (status as PartnerStatus | "all") : "applied";
  const { data: partners = [] } = await (await authedApi()).GET("/admin/partners", {
    params: { query: active === "all" ? {} : { status: active } },
  });

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Partner applications</h1>
      <nav className="flex gap-1 overflow-x-auto border-b border-zinc-200 dark:border-zinc-800" aria-label="Filter by status">
        {TABS.map((tab) => (
          <Link
            key={tab}
            href={`/admin/partners?status=${tab}`}
            aria-current={tab === active ? "page" : undefined}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${
              tab === active
                ? "border-emerald-600 text-zinc-900 dark:text-zinc-50"
                : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
            }`}
          >
            {tab === "all" ? "All" : STATUS_LABELS[tab]}
          </Link>
        ))}
      </nav>
      {partners.length === 0 ? (
        <p className="rounded-xl border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700">
          No applications here.
        </p>
      ) : (
        <ul className="grid gap-2">
          {partners.map((partner) => (
            <li key={partner.user_id}>
              <Link
                href={`/admin/partners/${partner.user_id}`}
                className="flex items-center gap-4 rounded-xl border border-zinc-200 bg-white p-4 transition-colors hover:border-emerald-600 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <Avatar src={partner.avatar_url} name={partner.full_name || partner.email} size={44} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-zinc-900 dark:text-zinc-50">{partner.full_name || partner.email}</p>
                  <p className="truncate text-sm text-zinc-600 dark:text-zinc-400">
                    NTRP {formatNtrp(partner.ntrp_rating)}
                    {partner.background && ` · ${BACKGROUND_LABELS[partner.background]}`} · {partner.city}
                    {partner.region && `, ${partner.region}`}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge status={partner.status} />
                  {partner.submitted_at && (
                    <span className="text-xs text-zinc-500">{new Date(partner.submitted_at).toLocaleDateString()}</span>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
