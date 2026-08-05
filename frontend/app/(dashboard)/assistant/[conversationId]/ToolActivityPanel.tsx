import type { ToolActivityEntry } from "./messageViewModel";

const TYPE_LABELS: Record<ToolActivityEntry["type"], string> = {
  call: "呼叫",
  result: "結果",
};

// Step 12 Frontend Slice 5: native <details>/<summary> for default-collapsed
// disclosure -- no extra state or icon component needed. Entries render in
// arrival order, unpaired (see ToolActivityEntry's comment in
// messageViewModel.ts for why). `detail` is always either a JSON-stringified
// arguments object or a backend-provided summary string, never a raw tool
// result payload, so this never needs its own truncation logic.
export default function ToolActivityPanel({ entries }: { entries: ToolActivityEntry[] }) {
  return (
    <details className="mb-2 rounded-md border border-black/10 bg-foreground/5 px-2 py-1 text-xs dark:border-white/10">
      <summary className="cursor-pointer select-none text-foreground/60">
        工具使用紀錄（{entries.length}）
      </summary>
      <ul className="mt-1 flex flex-col gap-1">
        {entries.map((entry, index) => (
          <li key={index} className="text-foreground/70">
            <span className="font-medium">
              {TYPE_LABELS[entry.type]}：{entry.toolName}
            </span>
            <span className="block whitespace-pre-wrap break-words">{entry.detail}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
