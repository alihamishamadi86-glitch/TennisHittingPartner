"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { apiBrowser } from "@/lib/api/browser";
import { errorMessage } from "@/lib/api/errors";
import { NTRP_LEVELS, formatNtrp } from "@/lib/profile/labels";
import type { components } from "@/lib/api/schema";
import type { Question } from "@/lib/profile/types";

type LevelAnswers = components["schemas"]["LevelAnswersIn"];

type Suggestion = { ntrp_rating: number; description: string };

export function LevelPicker({ value, onChange }: { value: number | null; onChange: (value: number) => void }) {
  const [quizOpen, setQuizOpen] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200" id="ntrp-label">
        NTRP rating
      </span>
      <div role="radiogroup" aria-labelledby="ntrp-label" className="grid grid-cols-4 gap-2 sm:grid-cols-6">
        {NTRP_LEVELS.map((level) => {
          const selected = value === level;
          return (
            <button
              key={level}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(level)}
              className={`h-10 rounded-lg border text-sm font-semibold tabular-nums transition-colors ${
                selected
                  ? "border-emerald-600 bg-emerald-600 text-white"
                  : "border-zinc-300 text-zinc-800 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-200"
              }`}
            >
              {formatNtrp(level)}
            </button>
          );
        })}
      </div>
      {!quizOpen ? (
        <button
          type="button"
          onClick={() => setQuizOpen(true)}
          className="w-fit text-sm font-semibold text-emerald-700 hover:underline dark:text-emerald-400"
        >
          Not sure? Answer 6 quick questions
        </button>
      ) : (
        <LevelQuiz
          onUse={(rating) => {
            onChange(rating);
            setQuizOpen(false);
          }}
          onClose={() => setQuizOpen(false)}
        />
      )}
    </div>
  );
}

function LevelQuiz({ onUse, onClose }: { onUse: (rating: number) => void; onClose: () => void }) {
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [suggestion, setSuggestion] = useState<Suggestion>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    apiBrowser.GET("/levels/questionnaire").then(({ data, error }) => {
      if (!active) return;
      if (data) setQuestions(data.questions);
      else setError(errorMessage(error));
    });
    return () => {
      active = false;
    };
  }, []);

  async function suggest() {
    const { data, error } = await apiBrowser.POST("/levels/suggest", {
      body: answers as LevelAnswers, // complete: the button is disabled until every question is answered
    });
    if (data) setSuggestion(data);
    else setError(errorMessage(error));
  }

  const complete = questions !== null && questions.every((q) => q.key in answers);

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950">
      {error && <Alert tone="error">{error}</Alert>}
      {!questions && !error && <p className="text-sm text-zinc-500">Loading questions…</p>}
      {questions?.map((question) => (
        <fieldset key={question.key} className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-medium text-zinc-900 dark:text-zinc-100">{question.prompt}</legend>
          {question.options.map((option, index) => (
            <label key={option} className="flex cursor-pointer items-center gap-2.5 text-sm text-zinc-700 dark:text-zinc-300">
              <input
                type="radio"
                name={question.key}
                checked={answers[question.key] === index}
                onChange={() => {
                  setAnswers({ ...answers, [question.key]: index });
                  setSuggestion(undefined);
                }}
                className="h-4 w-4 accent-emerald-600"
              />
              {option}
            </label>
          ))}
        </fieldset>
      ))}
      {suggestion ? (
        <div className="flex flex-col gap-3 rounded-lg bg-white p-4 dark:bg-zinc-900">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Suggested level</p>
          <p className="text-3xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {formatNtrp(suggestion.ntrp_rating)}
          </p>
          <p className="text-sm text-zinc-700 dark:text-zinc-300">{suggestion.description}</p>
          <Button type="button" onClick={() => onUse(suggestion.ntrp_rating)}>
            Use {formatNtrp(suggestion.ntrp_rating)}
          </Button>
        </div>
      ) : (
        <div className="flex gap-2">
          <Button type="button" onClick={suggest} disabled={!complete}>
            Suggest my level
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
