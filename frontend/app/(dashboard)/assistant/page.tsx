// Rendered inside AssistantShell's main content region (assistant/layout.tsx)
// only for the brief moment before AssistantShell's auto-create effect
// (2026-08-26) redirects to a freshly created conversation -- landing on
// bare /assistant no longer requires clicking "+ 新對話" first. This text
// is a transient loading state, not a "please choose one" prompt; it only
// lingers if conversation creation fails (AssistantShell shows the error
// separately in the sidebar).
export default function AssistantIndexPage() {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <p className="text-sm text-foreground/60">正在建立新對話…</p>
    </div>
  );
}
