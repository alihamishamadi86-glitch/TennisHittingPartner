import { AuthHeading } from "@/components/auth/auth-heading";
import { VerifyEmail } from "@/components/auth/verify-email";
import { Alert } from "@/components/ui/alert";

export const metadata = { title: "Confirm email · Tennis Hitting Partner" };

export default async function VerifyEmailPage(props: PageProps<"/verify-email">) {
  const { token } = await props.searchParams;
  return (
    <>
      <AuthHeading title="Confirm your email" />
      {typeof token === "string" ? (
        <VerifyEmail token={token} />
      ) : (
        <Alert tone="error">This confirmation link is incomplete.</Alert>
      )}
    </>
  );
}
