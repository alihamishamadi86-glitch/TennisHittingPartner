"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";

export function ForgotPasswordForm() {
  const [sentTo, setSentTo] = useState<string>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email"));
    setPending(true);
    setError(undefined);
    const { error } = await apiBrowser.POST("/auth/forgot-password", { body: { email } });
    setPending(false);
    if (error) setError(errorMessage(error));
    else setSentTo(email);
  }

  if (sentTo) {
    return (
      <Alert tone="success">
        If an account exists for <strong>{sentTo}</strong>, we&apos;ve emailed a link to reset your password.
      </Alert>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <Field id="email" label="Email" type="email" autoComplete="email" required />
      <Button type="submit" disabled={pending}>
        {pending ? "Sending…" : "Send reset link"}
      </Button>
    </form>
  );
}
