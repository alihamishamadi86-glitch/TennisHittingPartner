"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import type { SelfServiceRole } from "@/lib/auth/types";

import { Divider, GoogleButton } from "./google-button";
import { RoleSelect } from "./role-select";

export function RegisterForm({ initialRole, googleEnabled }: { initialRole: SelfServiceRole | null; googleEnabled: boolean }) {
  const router = useRouter();
  const [role, setRole] = useState<SelfServiceRole | null>(initialRole);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!role) {
      setError("Choose whether you're a player or a hitting partner.");
      return;
    }
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/auth/register", {
      body: {
        role,
        full_name: String(form.get("full_name")),
        email: String(form.get("email")),
        password: String(form.get("password")),
      },
    });
    if (!data) {
      setError(errorMessage(error));
      setPending(false);
      return;
    }
    router.replace("/onboarding/profile");
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-5">
      <RoleSelect value={role} onChange={setRole} />
      {googleEnabled && (
        <>
          <GoogleButton role={role ?? undefined} label="Sign up with Google" />
          <Divider />
        </>
      )}
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Field id="full_name" label="Full name" autoComplete="name" required />
        <Field id="email" label="Email" type="email" autoComplete="email" required />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          minLength={10}
          hint="At least 10 characters."
          required
        />
        <Button type="submit" disabled={pending}>
          {pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </div>
  );
}
