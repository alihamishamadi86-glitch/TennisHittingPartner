"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { apiBrowser } from "@/lib/api/browser";
import type { components } from "@/lib/api/schema";

type Settings = components["schemas"]["NotificationSettingsOut"];

function message(error: unknown): string {
  const detail = (error as { detail?: { message?: string } | string } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  return detail?.message ?? "Something went wrong. Please try again.";
}

function Toggle({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className={`flex items-start justify-between gap-4 ${disabled ? "opacity-60" : "cursor-pointer"}`}>
      <span className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{label}</span>
        <span className="text-xs text-zinc-500">{description}</span>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-5 w-5 shrink-0 accent-emerald-600"
      />
    </label>
  );
}

export function NotificationSettings({ initial }: { initial: Settings }) {
  const [settings, setSettings] = useState(initial);
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function save(next: { sms_reminders: boolean; email_reminders: boolean }) {
    setError(undefined);
    const { data, error } = await apiBrowser.PUT("/me/notifications", { body: next });
    if (data) setSettings(data);
    else setError(message(error));
  }

  async function sendCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const phone = String(new FormData(event.currentTarget).get("phone"));
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/me/phone", { body: { phone } });
    setPending(false);
    if (data) setCodeSentTo(data.phone);
    else setError(message(error));
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code"));
    setPending(true);
    setError(undefined);
    const { data, error } = await apiBrowser.POST("/me/phone/verify", { body: { code } });
    setPending(false);
    if (data) {
      setSettings(data);
      setCodeSentTo(null);
    } else setError(message(error));
  }

  async function removePhone() {
    const { data } = await apiBrowser.DELETE("/me/phone");
    if (data) setSettings(data);
  }

  return (
    <div className="flex flex-col gap-6">
      {settings.sms_available && (
        <section className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Mobile number</h2>
          {settings.phone_verified ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-zinc-800 dark:text-zinc-200">
                <span className="font-medium tabular-nums">{settings.phone}</span>{" "}
                <span className="text-emerald-700 dark:text-emerald-400">· verified</span>
              </p>
              <Button type="button" variant="ghost" onClick={removePhone}>
                Remove
              </Button>
            </div>
          ) : codeSentTo ? (
            // Distinct keys: otherwise React reuses the phone <input> (and its value) for the code.
            <form key="code" onSubmit={verify} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <Field id="code" label={`Enter the 6-digit code sent to ${codeSentTo}`} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required />
              </div>
              <Button type="submit" disabled={pending}>
                {pending ? "Checking…" : "Verify"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setCodeSentTo(null)}>
                Change number
              </Button>
            </form>
          ) : (
            <form key="phone" onSubmit={sendCode} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <Field id="phone" label="Mobile number" type="tel" autoComplete="tel" placeholder="+1 512 555 0123" required />
              </div>
              <Button type="submit" disabled={pending}>
                {pending ? "Sending…" : "Text me a code"}
              </Button>
            </form>
          )}
        </section>
      )}

      <section className="flex flex-col gap-5 rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Session reminders</h2>
        <Toggle
          label="Email reminders"
          description="A day before and 2 hours before each session, plus a rebooking link afterwards."
          checked={settings.email_reminders}
          onChange={(value) => save({ sms_reminders: settings.sms_reminders, email_reminders: value })}
        />
        {settings.sms_available && (
          <>
            <Toggle
              label="Text reminders"
              description={settings.phone_verified ? "Same reminders by SMS. No texts between 9 pm and 8 am." : "Verify your mobile number first."}
              checked={settings.sms_reminders}
              disabled={!settings.phone_verified}
              onChange={(value) => save({ sms_reminders: value, email_reminders: settings.email_reminders })}
            />
            <p className="text-xs leading-5 text-zinc-500">
              By turning on text reminders you agree to receive automated texts about your sessions from Tennis Hitting
              Partner. Message frequency varies; message and data rates may apply. Reply STOP to opt out at any time.
            </p>
          </>
        )}
      </section>

      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}
