"use client";

import { useEffect, useState } from "react";
import IconButton from "@/components/ui/IconButton";

export default function AppShell({
  sidebar,
  topNav,
  children,
}: {
  sidebar: React.ReactNode;
  topNav: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

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
          onClick={() => setOpen(false)}
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
            onClick={() => setOpen((value) => !value)}
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
