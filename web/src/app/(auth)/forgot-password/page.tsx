import Link from "next/link";

import { AuthHeading } from "@/components/auth/auth-heading";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";

export const metadata = { title: "Reset password · Tennis Hitting Partner" };

export default function ForgotPasswordPage() {
  return (
    <>
      <AuthHeading title="Reset your password">We&apos;ll email you a link to choose a new one.</AuthHeading>
      <ForgotPasswordForm />
      <p className="mt-5 text-center text-sm">
        <Link href="/login" className="font-semibold text-emerald-700 hover:underline dark:text-emerald-400">
          Back to sign in
        </Link>
      </p>
    </>
  );
}
