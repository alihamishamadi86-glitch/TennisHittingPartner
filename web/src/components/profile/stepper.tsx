"use client";

import type { ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export type Step = { title: string; description?: string; content: ReactNode; canContinue: boolean };

export function Stepper({
  steps,
  index,
  onIndexChange,
  error,
  finishActions,
}: {
  steps: Step[];
  index: number;
  onIndexChange: (index: number) => void;
  error?: ReactNode;
  finishActions: ReactNode;
}) {
  const step = steps[index];
  const last = index === steps.length - 1;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <div className="flex gap-1.5" aria-hidden>
          {steps.map((s, i) => (
            <span key={s.title} className={`h-1.5 flex-1 rounded-full ${i <= index ? "bg-emerald-600" : "bg-zinc-200 dark:bg-zinc-800"}`} />
          ))}
        </div>
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Step {index + 1} of {steps.length}
        </p>
        <div className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{step.title}</h2>
          {step.description && <p className="text-sm text-zinc-600 dark:text-zinc-400">{step.description}</p>}
        </div>
      </div>
      <div className="flex flex-col gap-5">{step.content}</div>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex flex-col-reverse gap-2 border-t border-zinc-200 pt-5 sm:flex-row sm:justify-between dark:border-zinc-800">
        <Button type="button" variant="ghost" onClick={() => onIndexChange(index - 1)} disabled={index === 0}>
          Back
        </Button>
        {last ? (
          <div className="flex flex-col-reverse gap-2 sm:flex-row">{finishActions}</div>
        ) : (
          <Button type="button" onClick={() => onIndexChange(index + 1)} disabled={!step.canContinue}>
            Continue
          </Button>
        )}
      </div>
    </div>
  );
}
