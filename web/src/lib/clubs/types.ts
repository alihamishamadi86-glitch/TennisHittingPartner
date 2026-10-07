import type { components } from "@/lib/api/schema";

export type City = components["schemas"]["CityOut"];
export type Club = components["schemas"]["ClubOut"];
export type ClubKind = components["schemas"]["ClubKind"];

export type MapTiles = { url: string; attribution: string };

export const KIND_LABELS: Record<ClubKind, string> = {
  club: "Club",
  sports_centre: "Tennis centre",
  public_courts: "Public courts",
};
