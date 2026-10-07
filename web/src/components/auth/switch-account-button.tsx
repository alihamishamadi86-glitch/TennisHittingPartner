"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";

/** Sign out, then sign in again and come back to `returnTo`. */
export function SwitchAccountButton({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  return (
    <Button
      type="button"
      onClick={async () => {
        await apiBrowser.POST("/auth/logout");
        router.replace(`/login?next=${encodeURIComponent(returnTo)}`);
        router.refresh();
      }}
    >
      Switch account
    </Button>
  );
}
