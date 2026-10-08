import "server-only";

import type { MapTiles } from "@/lib/clubs/types";

/** Tile server is runtime config so production can switch providers without a rebuild. */
export function mapTiles(): MapTiles {
  return {
    url: process.env.MAP_TILE_URL ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      process.env.MAP_TILE_ATTRIBUTION ??
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  };
}
