"use client";

import { useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { RequestPhase } from "./ChatThread";

// Step 12 Frontend Slice 4: purely controlled by ChatThread's phase --
// this component owns only the text field's local value, no network
// lifecycle. No role mode selector here (out of scope for this Slice).
export default function Composer({
  phase,
  onSend,
  onStop,
}: {
  phase: RequestPhase;
  onSend: (content: string) => void;
  onStop: () => void;
}) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isBusy = phase === "connecting" || phase === "streaming" || phase === "stopping";
  const canSend = !isBusy && value.trim() !== "";

  function handleSubmit() {
    if (!canSend) return;
    onSend(value);
    setValue("");
    textareaRef.current?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="flex items-end gap-2 border-t border-black/10 p-3 dark:border-white/10">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        placeholder="輸入訊息，Enter 送出、Shift+Enter 換行"
        className="min-h-9 flex-1 resize-none rounded-md border border-black/10 bg-background px-3 py-2 text-sm outline-none focus:border-foreground/30 dark:border-white/10"
      />
      {(phase === "connecting" || phase === "streaming") && (
        <button
          type="button"
          onClick={onStop}
          className="rounded-md border border-black/10 px-3 py-2 text-sm hover:bg-foreground/5 dark:border-white/10"
        >
          Stop
        </button>
      )}
      {phase === "stopping" && (
        <button
          type="button"
          disabled
          className="rounded-md border border-black/10 px-3 py-2 text-sm opacity-50 dark:border-white/10"
        >
          停止中…
        </button>
      )}
      {!isBusy && (
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSend}
          className="rounded-md border border-black/10 px-3 py-2 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
        >
          送出
        </button>
      )}
    </div>
  );
}
