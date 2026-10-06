"use client";

import { useState } from "react";

import { apiBrowser } from "@/lib/api/browser";

export function ResendVerification() {
  const [sent, setSent] = useState(false);
  if (sent) return <span className="font-medium">Sent — check your inbox.</span>;
  return (
    <button
      type="button"
      className="font-semibold underline underline-offset-2"
      onClick={async () => {
        await apiBrowser.POST("/auth/verify-email/resend");
        setSent(true);
      }}
    >
      Resend email
    </button>
  );
}
