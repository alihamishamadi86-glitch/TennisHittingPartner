"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { buttonClasses } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";

/**
 * Verifies on mount via POST rather than on the server-rendered GET, so link scanners in email
 * clients (which fetch but don't run JavaScript) can't consume the single-use token.
 */
export function VerifyEmail({ token }: { token: string }) {
  const [state, setState] = useState<{ status: "pending" | "done" | "error"; message?: string }>({ status: "pending" });
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    apiBrowser.POST("/auth/verify-email", { body: { token } }).then(({ data, error }) => {
      setState(data ? { status: "done" } : { status: "error", message: errorMessage(error) });
    });
  }, [token]);

  if (state.status === "pending") return <Alert>Confirming your email…</Alert>;
  if (state.status === "error") return <Alert tone="error">{state.message}</Alert>;
  return (
    <div className="flex flex-col gap-4">
      <Alert tone="success">Your email is confirmed.</Alert>
      <Link href="/dashboard" className={buttonClasses()}>
        Continue
      </Link>
    </div>
  );
}
