"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";

export function LogoutButton() {
  const router = useRouter();
  return (
    <Button
      variant="ghost"
      onClick={async () => {
        await apiBrowser.POST("/auth/logout");
        router.replace("/login");
        router.refresh();
      }}
    >
      Sign out
    </Button>
  );
}
