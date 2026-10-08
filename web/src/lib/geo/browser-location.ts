import { apiBrowser } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";

export type ReverseAddress = components["schemas"]["ReverseOut"];
export type DetectedLocation = { lat: number; lon: number; address: ReverseAddress };

export class LocationError extends Error {}

/** Current permission without prompting: "granted" | "denied" | "prompt" | "unsupported". */
export async function locationPermission(): Promise<PermissionState | "unsupported"> {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) return "unsupported";
  try {
    return (await navigator.permissions.query({ name: "geolocation" })).state;
  } catch {
    return "prompt"; // Permissions API missing (older Safari): asking is the only way to know
  }
}

function currentPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!window.isSecureContext) {
      reject(new LocationError("Location needs a secure (https) connection."));
      return;
    }
    if (!("geolocation" in navigator)) {
      reject(new LocationError("Your browser doesn't share location."));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, (error) => {
      const messages: Record<number, string> = {
        [error.PERMISSION_DENIED]: "Location access is blocked. Allow it in your browser's site settings, or type your city.",
        [error.POSITION_UNAVAILABLE]: "We couldn't determine your location. Please type your city.",
        [error.TIMEOUT]: "Finding your location took too long. Please try again or type your city.",
      };
      reject(new LocationError(messages[error.code] ?? "We couldn't get your location."));
    }, { enableHighAccuracy: false, timeout: 15_000, maximumAge: 5 * 60_000 });
  });
}

/** Ask the browser for the user's position (prompts if needed) and resolve it to an address. */
export async function detectLocation(): Promise<DetectedLocation> {
  const { coords } = await currentPosition();
  const { data } = await apiBrowser.GET("/geo/reverse", {
    params: { query: { lat: coords.latitude, lon: coords.longitude } },
  });
  if (!data) throw new LocationError("We couldn't tell which city you're in. Please type it.");
  return { lat: coords.latitude, lon: coords.longitude, address: data };
}
