"use client";

import { useState } from "react";

import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { COUNTRIES, HAND_LABELS, STYLE_LABELS } from "@/lib/profile/labels";
import type { DominantHand, PlayStyle } from "@/lib/profile/types";

import { LevelPicker } from "./level-picker";

export type LevelState = {
  ntrp_rating: number | null;
  utr_rating: string;
  years_playing: string;
  dominant_hand: DominantHand | "";
  play_style: PlayStyle | "";
  city: string;
  region: string;
  postal_code: string;
  country_code: string;
};

type LevelInitial = Partial<{
  ntrp_rating: number;
  utr_rating: number | null;
  years_playing: number | null;
  dominant_hand: DominantHand | null;
  play_style: PlayStyle | null;
  city: string;
  region: string | null;
  postal_code: string | null;
  country_code: string;
}>;

export function useLevelState(initial: LevelInitial | null) {
  return useState<LevelState>({
    ntrp_rating: initial?.ntrp_rating ?? null,
    utr_rating: initial?.utr_rating?.toString() ?? "",
    years_playing: initial?.years_playing?.toString() ?? "",
    dominant_hand: initial?.dominant_hand ?? "",
    play_style: initial?.play_style ?? "",
    city: initial?.city ?? "",
    region: initial?.region ?? "",
    postal_code: initial?.postal_code ?? "",
    country_code: initial?.country_code ?? "US",
  });
}

/** Convert form state to the API payload shape. */
export function levelPayload(state: LevelState) {
  return {
    ntrp_rating: state.ntrp_rating ?? 0,
    utr_rating: state.utr_rating ? Number(state.utr_rating) : null,
    years_playing: state.years_playing ? Number(state.years_playing) : null,
    dominant_hand: state.dominant_hand || null,
    play_style: state.play_style || null,
    city: state.city.trim(),
    region: state.region.trim() || null,
    postal_code: state.postal_code.trim() || null,
    country_code: state.country_code,
  };
}

type Props = { state: LevelState; setState: (state: LevelState) => void };

export function GameFields({ state, setState }: Props) {
  const set = <K extends keyof LevelState>(key: K, value: LevelState[K]) => setState({ ...state, [key]: value });
  return (
    <>
      <LevelPicker value={state.ntrp_rating} onChange={(value) => set("ntrp_rating", value)} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          id="dominant_hand"
          label="Dominant hand"
          placeholder="Select…"
          options={Object.entries(HAND_LABELS)}
          value={state.dominant_hand}
          onChange={(e) => set("dominant_hand", e.target.value as DominantHand | "")}
        />
        <Select
          id="play_style"
          label="Play style"
          placeholder="Select…"
          options={Object.entries(STYLE_LABELS)}
          value={state.play_style}
          onChange={(e) => set("play_style", e.target.value as PlayStyle | "")}
        />
        <Field
          id="years_playing"
          label="Years playing"
          type="number"
          inputMode="numeric"
          min={0}
          max={80}
          value={state.years_playing}
          onChange={(e) => set("years_playing", e.target.value)}
        />
        <Field
          id="utr_rating"
          label="UTR (optional)"
          type="number"
          inputMode="decimal"
          step="0.01"
          min={1}
          max={16.5}
          value={state.utr_rating}
          onChange={(e) => set("utr_rating", e.target.value)}
        />
      </div>
    </>
  );
}

export function LocationFields({ state, setState }: Props) {
  const set = <K extends keyof LevelState>(key: K, value: LevelState[K]) => setState({ ...state, [key]: value });
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Field id="city" label="City" autoComplete="address-level2" value={state.city} onChange={(e) => set("city", e.target.value)} required />
      </div>
      <Field
        id="region"
        label="State / province"
        autoComplete="address-level1"
        value={state.region}
        onChange={(e) => set("region", e.target.value)}
      />
      <Field
        id="postal_code"
        label="Postal code (optional)"
        autoComplete="postal-code"
        hint="Helps us show the closest courts first."
        value={state.postal_code}
        onChange={(e) => set("postal_code", e.target.value)}
      />
      <Select id="country_code" label="Country" options={COUNTRIES} value={state.country_code} onChange={(e) => set("country_code", e.target.value)} />
    </div>
  );
}
