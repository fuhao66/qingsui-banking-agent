import { SecureChannelAction } from "@/components/secure-channel-action";

export default async function SecureActionPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SecureChannelAction token={token} />;
}
