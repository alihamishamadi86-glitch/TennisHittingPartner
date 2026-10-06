import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthHeading } from "@/components/auth/auth-heading";
import { RegisterForm } from "@/components/auth/register-form";
import { getCurrentUser, googleSignInEnabled } from "@/lib/auth/server";

export const metadata = { title: "Create account · Tennis Hitting Partner" };

export default async function RegisterPage(props: PageProps<"/register">) {
  if (await getCurrentUser()) redirect("/dashboard");
  const { role } = await props.searchParams;
  const initialRole = role === "client" || role === "partner" ? role : null;

  return (
    <>
      <AuthHeading title="Create your account">Tell us how you&apos;ll use the platform.</AuthHeading>
      <RegisterForm initialRole={initialRole} googleEnabled={await googleSignInEnabled()} />
      <p className="mt-5 text-center text-sm text-zinc-600 dark:text-zinc-400">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-emerald-700 hover:underline dark:text-emerald-400">
          Sign in
        </Link>
      </p>
    </>
  );
}
