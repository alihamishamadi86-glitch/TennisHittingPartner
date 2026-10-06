"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import { BACKGROUND_LABELS, MISSING_LABELS } from "@/lib/profile/labels";
import type { PartnerBackground, PartnerProfile } from "@/lib/profile/types";

import { GameFields, LocationFields, levelPayload, useLevelState } from "./level-fields";
import { PhotoUpload } from "./photo-upload";
import { Stepper, type Step } from "./stepper";

const MIN_BIO = 80;

export function PartnerProfileForm({
  initial,
  name,
  avatarUrl,
}: {
  initial: PartnerProfile | null;
  name: string;
  avatarUrl: string | null;
}) {
  const router = useRouter();
  const [level, setLevel] = useLevelState(initial);
  const [background, setBackground] = useState<PartnerBackground | "">(initial?.background ?? "");
  const [bio, setBio] = useState(initial?.bio ?? "");
  const [radius, setRadius] = useState(String(initial?.service_radius_km ?? 15));
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<ReactNode>();
  const [pending, setPending] = useState<"save" | "submit" | null>(null);

  const canSubmit = !initial || initial.status === "draft" || initial.status === "rejected";

  async function save(submit: boolean) {
    setPending(submit ? "submit" : "save");
    setError(undefined);
    const saved = await apiBrowser.PUT("/me/partner-profile", {
      body: {
        ...levelPayload(level),
        background: background || null,
        bio,
        service_radius_km: Number(radius) || 15,
      },
    });
    if (!saved.data) {
      setError(errorMessage(saved.error));
      setPending(null);
      return;
    }
    if (submit) {
      const submitted = await apiBrowser.POST("/me/partner-profile/submit");
      if (!submitted.data) {
        const detail = (submitted.error as { detail?: { missing?: string[] } } | undefined)?.detail;
        setError(
          detail?.missing ? (
            <>
              Almost there — before submitting:
              <ul className="mt-1 list-disc pl-5">
                {detail.missing.map((key) => (
                  <li key={key}>{MISSING_LABELS[key] ?? key}</li>
                ))}
              </ul>
            </>
          ) : (
            errorMessage(submitted.error)
          ),
        );
        setPending(null);
        return;
      }
    }
    router.replace("/dashboard");
    router.refresh();
  }

  const steps: Step[] = [
    {
      title: "Your game",
      description: "Clients book partners at or above their level. We'll confirm yours at screening.",
      content: (
        <>
          <GameFields state={level} setState={setLevel} />
          <Select
            id="background"
            label="Playing background"
            placeholder="Select…"
            options={Object.entries(BACKGROUND_LABELS)}
            value={background}
            onChange={(e) => setBackground(e.target.value as PartnerBackground | "")}
          />
        </>
      ),
      canContinue: level.ntrp_rating !== null,
    },
    {
      title: "About you",
      description: "Clients choose partners from their photo and bio.",
      content: (
        <>
          <PhotoUpload name={name} initialUrl={avatarUrl} />
          <Textarea
            id="bio"
            label="Bio"
            maxLength={2000}
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder="Where you've played, your style, and what a session with you is like."
            hint={bio.trim().length < MIN_BIO ? `${MIN_BIO - bio.trim().length} more characters needed` : `${bio.length}/2000`}
          />
        </>
      ),
      canContinue: true,
    },
    {
      title: "Where you play",
      description: "Your home base and how far you'll travel to a court.",
      content: (
        <>
          <LocationFields state={level} setState={setLevel} />
          <Field
            id="service_radius_km"
            label="Travel radius (km)"
            type="number"
            inputMode="numeric"
            min={1}
            max={100}
            value={radius}
            onChange={(e) => setRadius(e.target.value)}
          />
        </>
      ),
      canContinue: level.city.trim().length > 0,
    },
  ];

  return (
    <Stepper
      steps={steps}
      index={index}
      onIndexChange={setIndex}
      error={error}
      finishActions={
        canSubmit ? (
          <>
            <Button type="button" variant="secondary" onClick={() => save(false)} disabled={pending !== null || !level.city.trim()}>
              {pending === "save" ? "Saving…" : "Save draft"}
            </Button>
            <Button type="button" onClick={() => save(true)} disabled={pending !== null || !level.city.trim()}>
              {pending === "submit" ? "Submitting…" : initial?.status === "rejected" ? "Resubmit application" : "Submit application"}
            </Button>
          </>
        ) : (
          <Button type="button" onClick={() => save(false)} disabled={pending !== null || !level.city.trim()}>
            {pending ? "Saving…" : "Save changes"}
          </Button>
        )
      }
    />
  );
}
