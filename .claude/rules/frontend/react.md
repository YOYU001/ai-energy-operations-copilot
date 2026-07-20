# Frontend / React 慣例

## 產品定位

整體介面在排版與互動體驗上，目標是做到接近 ChatGPT 的水準——尤其是 `/assistant`（AI Assistant / 角色化 Copilot 對話，對應 MVP v1 Scope 第 9 項）這個頁面，應該提供類似 ChatGPT 的對話式體驗（訊息串、輸入框、清楚的角色區分等）。

**與 ChatGPT 的關鍵差異**：ChatGPT 主要靠即時網路搜尋或使用者上傳的內容作答；本專案的企業 AI 小助手預設以**內部資料**作答（uploaded documents、imported CSV datasets、case records、built-in MVP rules），這是 `CLAUDE.md`「資料與回答原則」裡明訂的 Internal Knowledge Only 預設模式，不可繞過。

**外部搜尋切換（重要：目前僅為 UI 佔位，功能不可實作）**：`CLAUDE.md` 的 MVP v1 範圍明確把 Real web search 列為 Out of Scope，除非使用者另外明確核准並補上對應的 ADR，才能真的接上外部搜尋。因此：
- 介面上可以有「內部 / 外部」的切換元件（例如 toggle 或下拉選單），視覺與互動設計上先做出來。
- 但外部搜尋分支必須是 disabled 狀態，或明確顯示「此功能尚未開放」，**不可以**接任何真正呼叫外部網路的邏輯。
- 若之後要把這個功能轉正，必須先回到 `CLAUDE.md` 走範圍變更流程（更新 Out of Scope 清單 + 補一筆 `docs/DECISIONS.md` ADR），不是前端自己解禁。

## 既有慣例（依目前 `frontend/` 實際程式碼歸納，非憑空預設）

- **Server Component 為預設**，只有真的需要 client-side state/effect（例如 `AppShell.tsx` 的 mobile drawer 開關）才加 `"use client"`。
- **`lib/api/` 是呼叫 backend 的唯一入口**：`client.ts`（`server-only` + `fetch`，明確區分 timeout / network error / non-OK / 非 JSON 四種失敗情境並各自丟出有意義的錯誤訊息）+ `types.ts`（純 interface 定義）。頁面元件不直接呼叫 `fetch`。
- **用 runtime type guard 驗證 API response**（例如 `isHealthResponse`），不要用 `as SomeType` 直接硬轉型，避免 backend response 形狀跟前端假設不一致時無聲失敗。
- **`components/layout/` 用 PascalCase 檔名**，一個檔案一個 component。
- **Import 一律走 `@/*` path alias**（對應 repo root），不要用相對路徑往上跳多層（`../../..`）。
- **需要即時 backend 資料的頁面**，明確標註 `export const dynamic = "force-dynamic"`，不要依賴 Next.js 預設的靜態快取行為。
- **Tailwind dark mode 成對寫**，例如 `border-black/10 dark:border-white/10`，不要只寫 light mode 忘記補 dark。
- **UI 文字（使用者看得到的）用繁體中文**（例如 `aria-label="開啟導覽選單"`、頁面說明文字），程式碼內的 comment 目前維持英文——這是既有程式碼的實際寫法，非另外規定，之後若要統一改繁體中文需另外討論。
