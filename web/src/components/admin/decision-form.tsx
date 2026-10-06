"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import { NTRP_LEVELS, formatNtrp } from "@/lib/profile/labels";
import type { PartnerStatus } from "@/lib/profile/types";

type Decision = "screened" | "approved" | "rejected";

// Mirrors the API's allowed admin transitions.
const ALLOWED: Partial<Record<PartnerStatus, Decision[]>> = {
  applied: ["screened", "approved", "rejected"],
  screened: ["approved", "rejected"],
  approved: ["rejected"],
};

const LABELS: Record<Decision, string> = {
  screened: "Mark screened",
  approved: "Approve",
  rejected: "Reject",
};

export function DecisionForm({ partnerId, status, selfRated }: { partnerId: string; status: PartnerStatus; selfRated: number }) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [verified, setVerified] = useState(formatNtrp(selfRated));
  const [pending, setPending] = useState<Decision | null>(null);
  const [error, setError] = useState<string>();
  const options = ALLOWED[status] ?? [];

  if (options.length === 0) {
    return <p className="text-sm text-zinc-500">No decisions available for this status.</p>;
  }

  async function decide(decision: Decision) {
    setPending(decision);
    setError(undefined);
    const { error } = await apiBrowser.POST("/admin/partners/{partner_id}/decision", {
      params: { path: { partner_id: partnerId } },
      body: {
        decision,
        note,
        verified_ntrp_rating: decision === "approved" ? Number(verified) : null,
      },
    });
    setPending(null);
    if (error) {
      setError(errorMessage(error));
      return;
    }
    setNote("");
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert tone="error">{error}</Alert>}
      {options.includes("approved") && (
        <Select
          id="verified_ntrp"
          label="Verified NTRP (on approval)"
          options={NTRP_LEVELS.map((level) => [formatNtrp(level), formatNtrp(level)])}
          value={verified}
          onChange={(e) => setVerified(e.target.value)}
        />
      )}
      <Textarea
        id="note"
        label="Note (sent to the partner)"
        rows={3}
        maxLength={1000}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex flex-col gap-2">
        {options.map((decision) => (
          <Button
            key={decision}
            type="button"
            variant={decision === "rejected" ? "secondary" : "primary"}
            onClick={() => decide(decision)}
            disabled={pending !== null}
          >
            {pending === decision ? "Saving…" : LABELS[decision]}
          </Button>
        ))}
      </div>
    </div>
  );
}
