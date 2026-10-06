"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ChipGroup } from "@/components/ui/chip-group";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import { GOAL_LABELS } from "@/lib/profile/labels";
import type { ClientGoal, ClientProfile } from "@/lib/profile/types";

import { GameFields, LocationFields, levelPayload, useLevelState } from "./level-fields";
import { Stepper, type Step } from "./stepper";

export function ClientProfileForm({ initial }: { initial: ClientProfile | null }) {
  const router = useRouter();
  const [level, setLevel] = useLevelState(initial);
  const [goals, setGoals] = useState<ClientGoal[]>(initial?.goals ?? []);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function save() {
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.PUT("/me/client-profile", { body: { ...levelPayload(level), goals } });
    if (!data) {
      setError(errorMessage(error));
      setPending(false);
      return;
    }
    router.replace("/dashboard");
    router.refresh();
  }

  const steps: Step[] = [
    {
      title: "Your level",
      description: "This is how we match you with the right hitting partner.",
      content: <GameFields state={level} setState={setLevel} />,
      canContinue: level.ntrp_rating !== null,
    },
    {
      title: "What do you want to work on?",
      description: "Pick any that apply — your partner will tailor the session.",
      content: <ChipGroup legend="Goals" options={GOAL_LABELS} value={goals} onChange={setGoals} />,
      canContinue: true,
    },
    {
      title: "Where do you play?",
      description: "We'll use this to find courts and partners near you.",
      content: <LocationFields state={level} setState={setLevel} />,
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
        <Button type="button" onClick={save} disabled={pending || !level.city.trim()}>
          {pending ? "Saving…" : initial ? "Save changes" : "Finish"}
        </Button>
      }
    />
  );
}
