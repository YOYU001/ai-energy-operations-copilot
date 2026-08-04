import { getConversations } from "@/lib/api/client";
import AssistantShell from "./AssistantShell";

export const dynamic = "force-dynamic";

export default async function AssistantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const page = await getConversations();
  return <AssistantShell initialConversations={page.items}>{children}</AssistantShell>;
}
