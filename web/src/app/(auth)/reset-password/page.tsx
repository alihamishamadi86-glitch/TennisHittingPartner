import { AuthHeading } from "@/components/auth/auth-heading";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";
import { Alert } from "@/components/ui/alert";

export const metadata = { title: "Choose a new password · Tennis Hitting Partner" };

export default async function ResetPasswordPage(props: PageProps<"/reset-password">) {
  const { token } = await props.searchParams;
  return (
    <>
      <AuthHeading title="Choose a new password" />
      {typeof token === "string" ? (
        <ResetPasswordForm token={token} />
      ) : (
        <Alert tone="error">This reset link is incomplete. Request a new one.</Alert>
      )}
    </>
  );
}
