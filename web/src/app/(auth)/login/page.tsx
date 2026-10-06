import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthHeading } from "@/components/auth/auth-heading";
import { Divider, GoogleButton } from "@/components/auth/google-button";
import { LoginForm } from "@/components/auth/login-form";
import { getCurrentUser, googleSignInEnabled } from "@/lib/auth/server";
import { safeNextPath } from "@/lib/auth/redirect";

export const metadata = { title: "Sign in · Tennis Hitting Partner" };

const ERRORS: Record<string, string> = {
  google: "Google sign-in didn't complete. Please try again.",
};

export default async function LoginPage(props: PageProps<"/login">) {
  const params = await props.searchParams;
  const next = safeNextPath(params.next);
  if (await getCurrentUser()) redirect(next);
  const error = typeof params.error === "string" ? ERRORS[params.error] : undefined;

  return (
    <>
      <AuthHeading title="Welcome back">Sign in to book and manage your sessions.</AuthHeading>
      <div className="flex flex-col gap-5">
        {(await googleSignInEnabled()) && (
          <>
            <GoogleButton next={next} />
            <Divider />
          </>
        )}
        <LoginForm next={next} initialError={error} />
        <p className="text-center text-sm text-zinc-600 dark:text-zinc-400">
          New here?{" "}
          <Link href="/register" className="font-semibold text-emerald-700 hover:underline dark:text-emerald-400">
            Create an account
          </Link>
        </p>
      </div>
    </>
  );
}
