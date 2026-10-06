import type { PartnerStatus } from "@/lib/profile/types";
import { STATUS_LABELS } from "@/lib/profile/labels";

const TONES: Record<PartnerStatus, string> = {
  draft: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  applied: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  screened: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({ status }: { status: PartnerStatus }) {
  return (
    <span className={`inline-flex w-fit rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONES[status]}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
