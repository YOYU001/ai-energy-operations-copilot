"use client";

import IconButton from "@/components/ui/IconButton";
import { THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

// No useState/useEffect needed: which icon shows is driven purely by the
// `dark:` CSS variant (wired to the `data-theme` attribute on <html> in
// globals.css), so there's no client/server mismatch to sync and nothing
// to set state for on mount.
export default function ThemeToggle() {
  function toggle() {
    const next: Theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage unavailable (e.g. Safari Private Browsing) -- the DOM
      // attribute above still updates the current page, it just won't
      // persist across reloads.
    }
  }

  return (
    <IconButton
      onClick={toggle}
      aria-label="切換亮色／暗色主題"
      className="text-sm"
    >
      <span className="dark:hidden">🌙</span>
      <span className="hidden dark:inline">☀️</span>
    </IconButton>
  );
}
