"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import type { Waiver } from "@/lib/bookings/types";

export function WaiverForm({ waiver, expectedName, onSigned }: { waiver: Waiver; expectedName: string; onSigned: () => void }) {
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function sign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fullName = String(new FormData(event.currentTarget).get("full_name"));
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/waiver/sign", { body: { full_name: fullName, agree } });
    setPending(false);
    if (data?.signed) onSigned();
    else setError(errorMessage(error));
  }

  return (
    <form onSubmit={sign} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{waiver.title}</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">Required once before your first session.</p>
      </div>
      <div
        tabIndex={0}
        className="max-h-64 overflow-y-auto whitespace-pre-line rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200"
      >
        {waiver.body}
      </div>
      <label className="flex items-start gap-2.5 text-sm text-zinc-800 dark:text-zinc-200">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 h-4 w-4 accent-emerald-600" />
        I have read and agree to the waiver above.
      </label>
      <Field id="full_name" label="Type your full name to sign" placeholder={expectedName} autoComplete="name" required />
      {error && <Alert tone="error">{error}</Alert>}
      <Button type="submit" disabled={!agree || pending} className="w-fit">
        {pending ? "Signing…" : "Sign waiver"}
      </Button>
    </form>
  );
}
