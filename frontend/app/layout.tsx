import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import AppShell from "@/components/layout/AppShell";
import Sidebar from "@/components/layout/Sidebar";
import TopNav from "@/components/layout/TopNav";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Energy Operations Copilot",
  description:
    "Energy operations dashboard, knowledge base, and AI copilot for solar PV, EMS, and battery scheduling.",
};

// Narrowly scoped try/catch: only the localStorage read can throw (Safari
// Private Browsing, storage-disabled policies). matchMedia itself never
// throws, so it must stay outside the try -- otherwise a localStorage
// failure would also skip the OS-preference check, not just the stored
// choice. Also registers a live matchMedia listener so the theme reacts to
// an OS-level change while the tab stays open (not just at load).
const THEME_INIT_SCRIPT = `
(function () {
  var mql = window.matchMedia("(prefers-color-scheme: dark)");
  function getStored() {
    try {
      return localStorage.getItem("${THEME_STORAGE_KEY}");
    } catch (e) {
      return null;
    }
  }
  function resolve() {
    var stored = getStored();
    return stored === "light" || stored === "dark" ? stored : (mql.matches ? "dark" : "light");
  }
  document.documentElement.dataset.theme = resolve();
  mql.addEventListener("change", function () {
    var stored = getStored();
    if (stored !== "light" && stored !== "dark") {
      document.documentElement.dataset.theme = mql.matches ? "dark" : "light";
    }
  });
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-Hant"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="h-full">
        <AppShell sidebar={<Sidebar />} topNav={<TopNav />}>
          {children}
        </AppShell>
      </body>
    </html>
  );
}
