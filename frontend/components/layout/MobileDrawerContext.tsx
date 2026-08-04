"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

// Step 12 Frontend Slice 2: single shared source of truth for which
// mobile drawer (if any) is open. Deliberately one value, not two
// independent booleans -- opening one drawer automatically closes the
// other by construction, with no separate synchronization logic needed.
export type DrawerId = "global-nav" | "conversation-list";

type MobileDrawerContextValue = {
  openDrawer: DrawerId | null;
  setOpenDrawer: (id: DrawerId | null) => void;
};

const MobileDrawerContext = createContext<MobileDrawerContextValue | null>(null);

export function MobileDrawerProvider({ children }: { children: React.ReactNode }) {
  const [openDrawer, setOpenDrawerState] = useState<DrawerId | null>(null);
  const setOpenDrawer = useCallback((id: DrawerId | null) => setOpenDrawerState(id), []);
  const value = useMemo(() => ({ openDrawer, setOpenDrawer }), [openDrawer, setOpenDrawer]);

  return <MobileDrawerContext.Provider value={value}>{children}</MobileDrawerContext.Provider>;
}

export function useMobileDrawer(): MobileDrawerContextValue {
  const ctx = useContext(MobileDrawerContext);
  if (!ctx) {
    throw new Error("useMobileDrawer must be used within a MobileDrawerProvider");
  }
  return ctx;
}
