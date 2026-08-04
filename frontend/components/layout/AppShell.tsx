"use client";

import { useEffect } from "react";
import IconButton from "@/components/ui/IconButton";
import { MobileDrawerProvider, useMobileDrawer } from "./MobileDrawerContext";

function AppShellInner({
  sidebar,
  topNav,
  children,
}: {
  sidebar: React.ReactNode;
  topNav: React.ReactNode;
  children: React.ReactNode;
}) {
  const { openDrawer, setOpenDrawer } = useMobileDrawer();
  const open = openDrawer === "global-nav";

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenDrawer(null);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, setOpenDrawer]);

  return (
    <div className="flex h-full">
      {/* Desktop sidebar: always visible at md and above */}
      <div className="hidden border-r border-black/10 dark:border-white/10 md:block">
        {sidebar}
      </div>

      {/* Mobile overlay: only rendered while drawer is open */}
      {open && (
        <div
          aria-hidden="true"
          onClick={() => setOpenDrawer(null)}
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
        />
      )}

      {/* Mobile drawer */}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-56 bg-background shadow-lg transition-transform duration-200 ease-in-out md:hidden ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {sidebar}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center">
          <IconButton
            aria-label={open ? "關閉導覽選單" : "開啟導覽選單"}
            aria-expanded={open}
            onClick={() => setOpenDrawer(open ? null : "global-nav")}
            className="m-2 md:hidden"
          >
            <span aria-hidden="true">☰</span>
          </IconButton>
          <div className="min-w-0 flex-1">{topNav}</div>
        </div>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

export default function AppShell(props: {
  sidebar: React.ReactNode;
  topNav: React.ReactNode;
  children: React.ReactNode;
}) {
  // Step 12 Frontend Slice 2: the provider lives here so any descendant
  // under `children` (e.g. the assistant page's own conversation-list
  // drawer) can share the same single openDrawer value via
  // useMobileDrawer() -- this is the only change from the previous local
  // useState; every existing dashboard page's drawer behavior is
  // unchanged (openDrawer is still only ever "global-nav" or null for
  // them).
  return (
    <MobileDrawerProvider>
      <AppShellInner {...props} />
    </MobileDrawerProvider>
  );
}
