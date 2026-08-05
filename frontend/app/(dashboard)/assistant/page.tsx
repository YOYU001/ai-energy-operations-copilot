// Step 12 Frontend Slice 2: "no conversation selected" placeholder,
// rendered inside AssistantShell's main content region (assistant/layout.tsx).
// Message history, Composer, and streaming are later slices.
export default function AssistantIndexPage() {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <p className="text-sm text-foreground/60">
        選擇左側的對話，或建立新的對話開始使用 AI Assistant。
      </p>
    </div>
  );
}
