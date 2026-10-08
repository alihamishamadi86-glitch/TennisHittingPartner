"use client";

import { useState } from "react";

import { detectLocation, LocationError, type DetectedLocation } from "@/lib/geo/browser-location";

/** "Use my location" link-button: asks the browser, reverse-geocodes, hands back the result. */
export function UseLocationButton({
  onLocated,
  label = "Use my location",
}: {
  onLocated: (location: DetectedLocation) => void;
  label?: string;
}) {
  const [state, setState] = useState<"idle" | "locating" | { error: string }>("idle");

  async function locate() {
    setState("locating");
    try {
      onLocated(await detectLocation());
      setState("idle");
    } catch (err) {
      setState({ error: err instanceof LocationError ? err.message : "We couldn't get your location." });
    }
  }

  return (
    <span className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={locate}
        disabled={state === "locating"}
        className="inline-flex w-fit items-center gap-1.5 text-sm font-semibold text-emerald-700 hover:underline disabled:opacity-60 dark:text-emerald-400"
      >
        <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
          <circle cx="12" cy="12" r="7" />
        </svg>
        {state === "locating" ? "Finding you…" : label}
      </button>
      {typeof state === "object" && <span className="text-xs text-red-700 dark:text-red-400">{state.error}</span>}
    </span>
  );
}
