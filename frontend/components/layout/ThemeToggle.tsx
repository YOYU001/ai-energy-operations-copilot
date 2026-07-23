"use client";

// No useState/useEffect needed: which icon shows is driven purely by the
// `dark:` CSS variant (wired to the `data-theme` attribute on <html> in
// globals.css), so there's no client/server mismatch to sync and nothing
// to set state for on mount.
export default function ThemeToggle() {
  function toggle() {
    const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="切換亮色／暗色主題"
      className="rounded-md p-2 text-sm hover:bg-foreground/10"
    >
      <span className="dark:hidden">🌙</span>
      <span className="hidden dark:inline">☀️</span>
    </button>
  );
}
