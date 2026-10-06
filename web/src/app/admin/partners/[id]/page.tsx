import Link from "next/link";
import { notFound } from "next/navigation";

import { DecisionForm } from "@/components/admin/decision-form";
import { Avatar } from "@/components/ui/avatar";
import { StatusBadge } from "@/components/ui/status-badge";
import { authedApi } from "@/lib/auth/server";
import { BACKGROUND_LABELS, HAND_LABELS, STATUS_LABELS, STYLE_LABELS, formatNtrp } from "@/lib/profile/labels";

export const metadata = { title: "Partner application · Admin" };

export default async function PartnerDetailPage(props: PageProps<"/admin/partners/[id]">) {
  const { id } = await props.params;
  const { data: partner } = await (await authedApi()).GET("/admin/partners/{partner_id}", {
    params: { path: { partner_id: id } },
  });
  if (!partner) notFound();
  const { profile } = partner;

  const facts: [string, string][] = [
    ["Self-rated NTRP", formatNtrp(profile.ntrp_rating)],
    ["Verified NTRP", profile.verified_ntrp_rating ? formatNtrp(profile.verified_ntrp_rating) : "—"],
    ["UTR", profile.utr_rating?.toString() ?? "—"],
    ["Background", profile.background ? BACKGROUND_LABELS[profile.background] : "—"],
    ["Years playing", profile.years_playing?.toString() ?? "—"],
    ["Hand", profile.dominant_hand ? HAND_LABELS[profile.dominant_hand] : "—"],
    ["Style", profile.play_style ? STYLE_LABELS[profile.play_style] : "—"],
    ["Location", [profile.city, profile.region, profile.country_code].filter(Boolean).join(", ")],
    ["Travel radius", `${profile.service_radius_km} km`],
  ];

  return (
    <div className="flex flex-col gap-6">
      <Link href="/admin/partners" className="w-fit text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
        ← All applications
      </Link>
      <div className="flex flex-wrap items-center gap-4">
        <Avatar src={partner.avatar_url} name={partner.full_name || partner.email} size={72} />
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{partner.full_name}</h1>
          <a href={`mailto:${partner.email}`} className="text-sm text-zinc-600 hover:underline dark:text-zinc-400">
            {partner.email}
          </a>
          <StatusBadge status={partner.status} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-6">
          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-500">Profile</h2>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
              {facts.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-zinc-500">{label}</dt>
                  <dd className="font-medium text-zinc-900 dark:text-zinc-100">{value}</dd>
                </div>
              ))}
            </dl>
            <h3 className="mb-1 mt-5 text-sm text-zinc-500">Bio</h3>
            <p className="whitespace-pre-line text-sm text-zinc-800 dark:text-zinc-200">{profile.bio || "—"}</p>
          </section>

          <section className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-500">History</h2>
            <ol className="flex flex-col gap-3">
              {partner.history.map((entry) => (
                <li key={entry.created_at} className="text-sm">
                  <p className="text-zinc-900 dark:text-zinc-100">
                    {STATUS_LABELS[entry.from_status]} → <strong>{STATUS_LABELS[entry.to_status]}</strong>
                    <span className="text-zinc-500"> · {new Date(entry.created_at).toLocaleString()}</span>
                  </p>
                  {entry.note && <p className="text-zinc-600 dark:text-zinc-400">“{entry.note}”</p>}
                </li>
              ))}
            </ol>
          </section>
        </div>

        <section className="h-fit rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-500">Decision</h2>
          <DecisionForm partnerId={partner.user_id} status={partner.status} selfRated={profile.ntrp_rating} />
        </section>
      </div>
    </div>
  );
}
