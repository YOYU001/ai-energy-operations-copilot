"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { uploadDocumentAction } from "./actions";

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "processing"; fileName: string }
  | { kind: "already_ingested"; fileName: string }
  | { kind: "error"; message: string };

function messageForErrorStatus(status: number | null): string {
  if (status === 415) return "不支援的檔案格式：目前僅支援 PDF。";
  if (status === 400) return "檔案內容無效（例如空檔案），請確認後重新上傳。";
  return "上傳失敗，請稍後再試。";
}

export default function UploadDocumentForm() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      setSelectedFileName(null);
      return;
    }
    // Defensive re-check: the file input's accept=".pdf" already restricts
    // the OS picker's visible files, but drag-and-drop or an "all files"
    // override can still bypass that -- never rely on accept alone.
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setState({ kind: "error", message: "不支援的檔案格式：目前僅支援 PDF。" });
      setSelectedFileName(null);
      e.target.value = "";
      return;
    }
    setSelectedFileName(file.name);
    setState({ kind: "idle" });
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    setState({ kind: "uploading" });
    startTransition(async () => {
      const result = await uploadDocumentAction(formData);
      if (!result.ok) {
        setState({ kind: "error", message: messageForErrorStatus(result.status) });
        return;
      }
      setState(
        result.status === "already_ingested"
          ? { kind: "already_ingested", fileName: result.fileName }
          : { kind: "processing", fileName: result.fileName },
      );
      setSelectedFileName(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      router.refresh();
    });
  };

  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <p className="text-sm font-medium">上傳文件</p>
      <p className="mt-1 text-xs text-foreground/60">
        目前僅支援 PDF 格式（TXT / MD 尚未開放）。
      </p>
      <form onSubmit={handleSubmit} className="mt-3 flex flex-wrap items-center gap-3">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          onChange={handleFileChange}
          disabled={isPending}
          aria-label="選擇要上傳的 PDF 檔案"
          className="text-sm"
        />
        <button
          type="submit"
          disabled={isPending || !selectedFileName}
          className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
        >
          {isPending ? "上傳中..." : "上傳"}
        </button>
      </form>

      {state.kind === "error" && (
        <p className="mt-2 text-sm text-red-600">{state.message}</p>
      )}
      {state.kind === "processing" && (
        <p className="mt-2 text-sm text-emerald-700 dark:text-emerald-400">
          {state.fileName} 已上傳，正在處理中，完成後會自動更新下方列表狀態。
        </p>
      )}
      {state.kind === "already_ingested" && (
        <p className="mt-2 text-sm text-foreground/70">
          {state.fileName} 已存在且處理完成，本次上傳未建立新文件。
        </p>
      )}
    </div>
  );
}
