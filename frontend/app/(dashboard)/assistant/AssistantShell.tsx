"use client";

import { useEffect, useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import IconButton from "@/components/ui/IconButton";
import { useMobileDrawer } from "@/components/layout/MobileDrawerContext";
import type { ConversationSummary } from "@/lib/api/types";
import ConversationList from "./ConversationList";

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export default function AssistantShell({
  initialConversations,
  children,
}: {
  initialConversations: ConversationSummary[];
  children: React.ReactNode;
}) {
  const { openDrawer, setOpenDrawer } = useMobileDrawer();
  const isDrawerOpen = openDrawer === "conversation-list";
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams<{ conversationId?: string }>();
  const selectedId = params.conversationId ? Number(params.conversationId) : null;

  const [conversations, setConversations] = useState(initialConversations);
  // Step 12 review fix: initialConversations is re-supplied by the parent
  // server component on every router.refresh() (e.g. after the first
  // message auto-generates a title, or the backend re-sorts by
  // updated_at) -- but local state, once seeded via useState's initial
  // value, does not pick up later prop changes on its own. Without this,
  // the sidebar keeps showing stale titles/ordering until a hard reload.
  // Adjusted during render (react.dev's "adjusting state on prop change"
  // pattern), not in an effect, to avoid an extra render pass.
  const [prevInitialConversations, setPrevInitialConversations] = useState(initialConversations);
  if (initialConversations !== prevInitialConversations) {
    setPrevInitialConversations(initialConversations);
    setConversations(initialConversations);
  }

  const [isCreating, setIsCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Step 12 Frontend Slice 2: any route change (selecting a conversation,
  // being redirected back to /assistant after archiving the currently
  // selected one, etc.) closes the mobile conversation drawer. This does
  // NOT touch the global nav drawer or Sidebar.tsx at all -- that
  // behavior is unchanged from before this slice.
  useEffect(() => {
    if (isDrawerOpen) setOpenDrawer(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only pathname changes should trigger this
  }, [pathname]);

  useEffect(() => {
    if (!isDrawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenDrawer(null);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isDrawerOpen, setOpenDrawer]);

  async function handleCreate() {
    setIsCreating(true);
    setActionError(null);
    try {
      const res = await fetch("/api/assistant/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        throw new Error(await parseErrorDetail(res));
      }
      const created = (await res.json()) as ConversationSummary;
      setConversations((prev) => [created, ...prev]);
      router.push(`/assistant/${created.id}`);
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setIsCreating(false);
    }
  }

  async function handleArchive(id: number) {
    setActionError(null);
    try {
      const res = await fetch(`/api/assistant/conversations/${id}`, { method: "DELETE" });
      if (!res.ok) {
        throw new Error(await parseErrorDetail(res));
      }
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (selectedId === id) {
        router.push("/assistant");
      }
    } catch (error) {
      setActionError((error as Error).message);
    }
  }

  const sidebarContent = (
    <div className="flex h-full w-64 flex-col gap-3 px-3 py-4">
      <button
        type="button"
        onClick={handleCreate}
        disabled={isCreating}
        className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
      >
        {isCreating ? "建立中…" : "+ 新對話"}
      </button>
      {actionError && <p className="text-xs text-red-600 dark:text-red-400">{actionError}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ConversationList
          conversations={conversations}
          selectedId={selectedId}
          onArchive={handleArchive}
          onItemClick={() => setOpenDrawer(null)}
        />
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      {/* Desktop: fixed conversation sidebar, always visible, independent
          of any drawer state entirely. */}
      <div className="hidden border-r border-black/10 dark:border-white/10 md:block">
        {sidebarContent}
      </div>

      {/* Mobile: separate drawer from the global nav drawer, mutually
          exclusive via the shared MobileDrawerContext (section 6 of
          docs/step12_frontend_chat_ui_plan.md). */}
      {isDrawerOpen && (
        <div
          aria-hidden="true"
          onClick={() => setOpenDrawer(null)}
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-50 bg-background shadow-lg transition-transform duration-200 ease-in-out md:hidden ${
          isDrawerOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {sidebarContent}
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center border-b border-black/10 p-2 dark:border-white/10 md:hidden">
          <IconButton
            aria-label={isDrawerOpen ? "關閉對話列表" : "開啟對話列表"}
            aria-expanded={isDrawerOpen}
            onClick={() => setOpenDrawer(isDrawerOpen ? null : "conversation-list")}
          >
            <span aria-hidden="true">💬</span>
          </IconButton>
        </div>
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
