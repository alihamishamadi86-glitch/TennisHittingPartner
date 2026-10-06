import { Suspense } from "react";

import Link from "next/link";

import { ApiStatus } from "@/components/api-status";
import { buttonClasses } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center gap-8 px-4 py-24 sm:px-8">
      <div className="flex flex-col gap-4">
        <p className="text-sm font-medium uppercase tracking-widest text-emerald-600">
          Tennis Hitting Partner
        </p>
        <h1 className="text-4xl font-semibold tracking-tight text-zinc-900 sm:text-5xl dark:text-zinc-50">
          Book a skilled hitting partner near you.
        </h1>
        <p className="max-w-xl text-lg leading-8 text-zinc-600 dark:text-zinc-400">
          Live-ball rally practice and match play with vetted 4.5+ players, at the courts you
          already play on.
        </p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link href="/register?role=client" className={buttonClasses("primary")}>
          Book a hitting partner
        </Link>
        <Link href="/register?role=partner" className={buttonClasses("secondary")}>
          Become a partner
        </Link>
        <Link href="/login" className={buttonClasses("ghost")}>
          Sign in
        </Link>
      </div>
      <Suspense fallback={<p className="text-sm text-zinc-500">Checking API…</p>}>
        <ApiStatus />
      </Suspense>
    </main>
  );
}
