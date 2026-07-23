import ThemeToggle from "@/components/layout/ThemeToggle";

export default function TopNav() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-black/10 px-4 dark:border-white/10">
      <span className="text-base font-semibold">
        AI Energy Operations Copilot
      </span>
      <ThemeToggle />
    </header>
  );
}
