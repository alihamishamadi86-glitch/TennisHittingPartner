"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";

export function LoginForm({ next, initialError }: { next: string; initialError?: string }) {
  const router = useRouter();
  const [error, setError] = useState(initialError);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/auth/login", {
      body: { email: String(form.get("email")), password: String(form.get("password")) },
    });
    if (!data) {
      setError(errorMessage(error));
      setPending(false);
      return;
    }
    router.replace(data.role ? next : "/onboarding/role");
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <Field id="email" label="Email" type="email" autoComplete="email" required />
      <Field id="password" label="Password" type="password" autoComplete="current-password" required />
      <div className="-mt-1 text-right">
        <Link href="/forgot-password" className="text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          Forgot password?
        </Link>
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
