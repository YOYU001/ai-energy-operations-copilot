"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const POLL_INTERVAL_MS = 3000;

// Minimal auto-refresh for a single detail page while its document is still
// "processing" -- deliberately NOT a reuse of DocumentsList's polling
// logic (that inspects a whole list's statuses); this component only exists
// while the parent page's own status is "processing", so its mount/unmount
// lifecycle alone is enough to start/stop the interval.
export default function ProcessingAutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    const interval = setInterval(() => {
      router.refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [router]);

  return null;
}
