"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/overview", label: "Overview" },
  { href: "/datasets", label: "Datasets" },
  { href: "/documents", label: "Documents" },
  { href: "/analysis", label: "Analysis" },
  { href: "/assistant", label: "AI Assistant" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <nav aria-label="主要導覽" className="flex h-full w-56 flex-col px-3 py-4">
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`block rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-foreground/10 font-medium text-foreground"
                    : "text-foreground/70 hover:bg-foreground/5 hover:text-foreground"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
