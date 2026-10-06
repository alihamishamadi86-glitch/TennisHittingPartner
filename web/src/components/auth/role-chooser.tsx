"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import type { SelfServiceRole } from "@/lib/auth/types";

import { RoleSelect } from "./role-select";

export function RoleChooser() {
  const router = useRouter();
  const [role, setRole] = useState<SelfServiceRole | null>(null);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit() {
    if (!role) return;
    setPending(true);
    const { data, error } = await apiBrowser.PUT("/me/role", { body: { role } });
    if (!data) {
      setError(errorMessage(error));
      setPending(false);
      return;
    }
    router.replace("/dashboard");
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-5">
      {error && <Alert tone="error">{error}</Alert>}
      <RoleSelect value={role} onChange={setRole} />
      <Button onClick={submit} disabled={!role || pending}>
        {pending ? "Saving…" : "Continue"}
      </Button>
    </div>
  );
}
