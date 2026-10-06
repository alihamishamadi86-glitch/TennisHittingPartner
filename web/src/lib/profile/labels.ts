import type { ClientGoal, DominantHand, PartnerBackground, PartnerStatus, PlayStyle } from "./types";

export const NTRP_LEVELS = Array.from({ length: 12 }, (_, i) => 1.5 + i * 0.5);

export const HAND_LABELS: Record<DominantHand, string> = {
  right: "Right-handed",
  left: "Left-handed",
  ambidextrous: "Ambidextrous",
};

export const STYLE_LABELS: Record<PlayStyle, string> = {
  baseliner: "Baseliner",
  all_court: "All-court",
  serve_and_volley: "Serve & volley",
  counterpuncher: "Counterpuncher",
};

export const GOAL_LABELS: Record<ClientGoal, string> = {
  rally: "Rally practice",
  match_play: "Match play",
  fitness: "Fitness & cardio",
  technique: "Grooving technique",
};

export const BACKGROUND_LABELS: Record<PartnerBackground, string> = {
  professional: "Former or current pro",
  college: "College player",
  high_school_varsity: "High school varsity",
  club: "Club or league player",
  coach: "Coach",
  other: "Other",
};

export const STATUS_LABELS: Record<PartnerStatus, string> = {
  draft: "Draft",
  applied: "Under review",
  screened: "Screened",
  approved: "Approved",
  rejected: "Not approved",
};

export const MISSING_LABELS: Record<string, string> = {
  photo: "Add a profile photo",
  bio: "Write a bio of at least 80 characters",
  background: "Choose your playing background",
  ntrp_rating: "Partners need an NTRP rating of 4.5 or higher",
};

export const COUNTRIES: [string, string][] = [
  ["US", "United States"],
  ["CA", "Canada"],
  ["GB", "United Kingdom"],
  ["IE", "Ireland"],
  ["AU", "Australia"],
  ["NZ", "New Zealand"],
  ["AE", "United Arab Emirates"],
  ["FR", "France"],
  ["DE", "Germany"],
  ["ES", "Spain"],
  ["IT", "Italy"],
  ["NL", "Netherlands"],
];

export const formatNtrp = (value: number) => value.toFixed(1);
