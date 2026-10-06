"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button, buttonClasses } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";

export function ResetPasswordForm({ token }: { token: string }) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError("Passwords don't match.");
      return;
    }
    setPending(true);
    setError(undefined);
    const { error } = await apiBrowser.POST("/auth/reset-password", { body: { token, password } });
    setPending(false);
    if (error) setError(errorMessage(error));
    else setDone(true);
  }

  if (done) {
    return (
      <div className="flex flex-col gap-4">
        <Alert tone="success">Your password has been reset. You&apos;ve been signed out everywhere.</Alert>
        <Link href="/login" className={buttonClasses()}>
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <Field id="password" label="New password" type="password" autoComplete="new-password" hint="At least 10 characters." required />
      <Field id="confirm" label="Confirm new password" type="password" autoComplete="new-password" required />
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Set new password"}
      </Button>
    </form>
  );
}
