# Step 7: Frontend Foundation — Plan

> **狀態：已核准的 planning，尚未開始實作。** 本文件保存 Step 7 的完整規劃（含技術選型查證、API 連線決策、安全初始化流程），供 `/clear` 後的新 session 直接依此開始實作，不需要重新規劃或重新查證版本資訊。
> 定位：對應 `docs/DEVELOPMENT_WORKFLOW.md` 第 6 節 Step 7（Frontend Foundation），在 `docs/PROJECT_ALIGNMENT_REVIEW.md` §9 既有 roadmap 順序中，緊接在已 closeout 的 Step 6（RAG Feasibility Spike，commit `82fe7c3837723ae28dbd2e1459f382709de41881`）之後。

---

## 1. Step 7 目標與範圍

建立 Energy Operations Dashboard 的前端基礎架構：可擴充、可展示、能連接現有 FastAPI backend 的骨架，不急著完成完整圖表與 AI Assistant。對應 `docs/DEVELOPMENT_WORKFLOW.md` 第 7 節 First Milestone 第 5、6 點：「Dataset list 可以在前端顯示」「一個簡單 Dashboard 可以從 backend 讀資料」。

Step 7 範圍：Next.js 專案初始化、Dashboard layout（Sidebar/TopNav/main content）、5 個基礎頁面、與 FastAPI 的資料串接骨架、loading/error/empty 三態處理。**不包含**任何圖表繪製、AI Assistant 邏輯、認證、資料寫入（upload）。

---

## 2. Next.js Stable Exact Version 查證結果與 Node.js Requirement

已查閱 Next.js 官方文件（`nextjs.org/docs`，upgrade guide 標示版本 16.2.10，更新於 2026-05-13）與 npm registry（`registry.npmjs.org/next/latest` 實查回傳 `"version": "16.2.10"`）：

| 項目 | 版本 | 依據 |
|---|---|---|
| Next.js | **16.2.10**（stable，非 canary/RC/beta） | npm `latest` dist-tag 實查結果 |
| Node.js 最低需求 | **20.9.0+**（Node 18 已不支援） | Next.js 16 官方 upgrade guide |
| Node.js 建議版本 | **Node.js 24 LTS**（查證當下最新 patch 24.18.0，2026-06-23 發布） | Node.js 目前 Active LTS 是 24.x（22.x 已進入 Maintenance LTS，26.x 要到 2026-10 才轉正式 LTS），24.x 支援期限到 2028-04-30，是官方建議的「新專案應該用」版本 |
| TypeScript 最低需求 | **5.1.0+** | Next.js 16 官方 upgrade guide |

**選擇 Next.js 16（而非 15）的理由**：
- 16 是查證當下 npm `latest` dist-tag 指向的版本，非 pre-release，符合「不使用 canary/RC/beta」的要求。
- Turbopack 在 16 已是 stable 且預設啟用，不需要額外旗標。
- **Next.js 16 把 fetch 的預設行為改成完全不快取**（每次 request 即時拿最新資料，除非明確用 `"use cache"` opt-in）——直接簡化了 Datasets 頁面的資料新鮮度處理，不需要額外設定就能保證每次都看到 DB 最新內容。

**Node.js 版本注意事項**：24.18.0 是查證當下的最新 patch，patch 版本更新頻繁，實作前應該用 `node -v` 或 `nvm ls-remote --lts` 重新確認一次目前的 24.x 最新 patch，不應假設半年後這份文件寫的號碼還是最新的；但 major 版本（24 LTS）與最低需求（20.9+）的判斷依據不會因為 patch 更新而改變。

Sources（查證時使用的官方來源）：
- Next.js 官方文件：`https://nextjs.org/docs/app/guides/upgrading/version-16`
- npm registry：`https://registry.npmjs.org/next/latest`
- Next.js CLI 參考：`https://nextjs.org/docs/app/api-reference/cli/create-next-app`

---

## 3. TypeScript、App Router、Tailwind CSS 的採用理由

| 項目 | 決策 | 理由 |
|---|---|---|
| TypeScript | 採用 | API 回傳有明確 Pydantic schema（`backend/app/schemas.py`），前端用 TS 定義對應 interface 可及早抓到欄位對不上的錯誤；業界標準實踐，適合作品集呈現 |
| App Router | 採用（非 Pages Router） | Next.js 現行主流、資料夾結構即路由，天然適合本專案多頁面（Overview/Datasets/Documents/Analysis/Assistant）需求；且 Server Component 資料抓取模式（見第 4 節）只有 App Router 支援 |
| Tailwind CSS | 採用 | `create-next-app` 官方 scaffold 原生整合，設定成本低，不需要額外裝大型 UI library 就能做出一致骨架；呼應「避免過度依賴大型套件」與 `docs/DEVELOPMENT_WORKFLOW.md` 第 9 節「不要過早美化 UI」 |
| UI Library（Radix/shadcn/MUI/AntD 等） | **暫不導入** | Tailwind 本身已足夠做出乾淨骨架；提早引入會增加 bundle size、學習曲線與維護成本。等未來真的需要複雜元件（Modal/DataTable/Toast）時再評估輕量方案 |

---

## 4. API Connection 決策

**採用：Next.js Server Component 直接從 server side 呼叫 FastAPI。**

- **本 Step 不使用 Route Handler proxy**：Route Handler proxy 適合「瀏覽器需要主動觸發 API 呼叫」的情境（例如未來的 dataset 上傳表單、AI Assistant 即時對話），Step 7 全部 5 個頁面都是純顯示、沒有任何互動觸發重新查詢的需求，現在做屬於過度設計。留給未來真正需要 client-side 互動打 API 的 Step（可能是 Step 12 AI Assistant）再引入。
- **本 Step 不使用 browser client-side fetch**：同上，沒有互動需求，不需要在瀏覽器端發請求。
- **不修改 FastAPI CORS**：`page.tsx` 寫成 `async function`，在 server 端（Next.js 自己的 Node process）直接 `fetch(process.env.API_BASE_URL + "/datasets")`。這是 Next.js server 對 FastAPI server 的伺服器對伺服器請求，**完全不經過瀏覽器**，CORS 是瀏覽器強制執行的機制，伺服器對伺服器的請求不受 CORS 規則管轄。因此 `backend/app/main.py` 不需要加 `CORSMiddleware`——這不是「暫時」不需要，是這個架構下**從根本上不需要**。
- **環境變數**：只用 server-only 的 `API_BASE_URL`（無 `NEXT_PUBLIC_` 前綴），開發預設 `http://localhost:8000`，寫在 `.env.local.example`。**不使用 `NEXT_PUBLIC_API_BASE_URL`**——因為瀏覽器完全不需要知道 backend 的網址，用 `NEXT_PUBLIC_` 前綴反而會不必要地把這個設定暴露進瀏覽器端的 JS bundle。若未來真的引入 Route Handler proxy 或直接 client fetch，才需要重新評估是否要加 `NEXT_PUBLIC_` 版本。

---

## 5. Server Component 與 Client Component 分工

| 檔案 | 型態 | 理由 |
|---|---|---|
| `app/layout.tsx` | Server Component | 純組裝外框，無互動 |
| `app/overview/page.tsx` | Server Component（`async function`） | 直接 fetch `/health`/`/version`，純顯示 |
| `app/datasets/page.tsx` | Server Component（`async function`） | 直接 fetch `/datasets`，純顯示 |
| `app/documents/page.tsx`、`app/analysis/page.tsx`、`app/assistant/page.tsx` | Server Component | 純靜態 placeholder 文字，連 fetch 都不用 |
| `components/layout/TopNav.tsx` | Server Component | 純顯示，無互動狀態 |
| `components/ui/*`（Card/EmptyState/…） | Server Component | 純展示型，不需要 client state |
| `components/layout/Sidebar.tsx` | **Client Component**（`"use client"`） | 唯一需要瀏覽器端 state 的地方：手機寬度的收合/展開需要 `useState` |
| `app/*/error.tsx`（各路由的錯誤邊界） | **Client Component**（`"use client"`） | Next.js 框架規定：error boundary 必須是 Client Component，這是框架慣例要求，不是自選 |

整體只有 2 種檔案需要 `"use client"`：Sidebar 的收合互動、以及框架強制要求的 error boundary。其餘所有頁面與元件都是預設的 Server Component，沒有多餘的 client-side JavaScript。

---

## 6. loading.tsx、error.tsx、EmptyState 的設計

改用 Next.js App Router 內建的檔案慣例，而非手動 `useState`/`useEffect`（因為 Server Component 本身不能用 `useState`）：

- **Loading**：每個路由資料夾放一個 `loading.tsx`（例如 `app/datasets/loading.tsx`）。Next.js 在 `page.tsx` 的 async fetch 還沒回來前自動顯示這個檔案的內容（框架用 React Suspense 機制實作，不需要手寫 loading state 邏輯）。
- **Error**：每個路由資料夾放一個 `error.tsx`（例如 `app/datasets/error.tsx`）。當 `page.tsx` 的 fetch 丟出例外（例如 backend 沒啟動、connection refused）時，Next.js 自動改渲染這個檔案，內含官方標準的 `reset()` 函式讓使用者可以按「重試」。
- **Empty**：這是「成功拿到資料，但資料是空陣列」，不算錯誤也不算 loading，**在 `page.tsx` 本身處理**：fetch 成功後檢查 `data.length === 0`，是的話渲染 `components/ui/EmptyState.tsx`，不是的話渲染實際的表格。

三態分工：loading/error 是框架自動接管的「請求還沒完成」情境，empty 是「請求成功但沒東西」的業務邏輯，寫在頁面元件裡。

---

## 7. Frontend 安全初始化流程

**背景**：`frontend/` 現在不是空資料夾（已有 `README.md`）。已查證 `create-next-app` 原始碼（`is-folder-empty.ts`）：它只允許目標資料夾包含白名單內的安全檔案（`.git`、`.gitignore`、`LICENSE`、`docs`、各種 IDE 設定檔等），**`README.md` 不在白名單內**，直接對著 `frontend/` 跑會被判定為「非空、有衝突」而拒絕或跳出警告。

另外查到兩個必須注意的風險：
1. **`--agents-md` 在 16.2.10 是預設開啟**，會自動產生 `AGENTS.md` 與工具自己的 `CLAUDE.md`——本專案根目錄已有具體規範專案規則的 `CLAUDE.md`，若在 `frontend/` 裡再塞一份泛用的 `CLAUDE.md` 會造成混淆，**必須明確加 `--no-agents-md`**。
2. **`create-next-app` 預設會在新資料夾裡跑 `git init`**——本專案已是 git repo，若在 `frontend/` 子目錄裡再 `git init` 一次，會產生巢狀 git repo（nested repo），導致 `frontend/` 底下的檔案不會被外層 repo 正常追蹤，**必須明確加 `--disable-git`**。

**採用「暫存資料夾初始化後搬入」**：任何一步失敗時，已被 git 追蹤的 `frontend/` 完全不會被動到，只需清掉暫存資料夾即可重來，風險最低。

規劃的 command sequence（**Step 7 實作階段才執行，本次僅保存**）：

```bash
# 0. 確認現況，不動任何東西
git status
ls frontend/

# 1. 在 repo 之外的暫存目錄跑 scaffold，明確關閉 git init 與 agents-md，
#    明確指定 npm、TypeScript、Tailwind、App Router、ESLint
npx create-next-app@16.2.10 <scratchpad>/frontend_scaffold_staging \
  --typescript --tailwind --app --eslint \
  --import-alias "@/*" --use-npm --disable-git --no-agents-md --yes

# 2. 先檢查暫存目錄產生了什麼，人工確認沒有意外檔案，再繼續
ls -la <scratchpad>/frontend_scaffold_staging
cat <scratchpad>/frontend_scaffold_staging/package.json

# 3. 備份現有的 frontend/README.md（改名保留，不是刪除）
mv frontend/README.md frontend/README.md.original

# 4. 把暫存資料夾的內容（含隱藏檔）複製進 frontend/
cp -r <scratchpad>/frontend_scaffold_staging/. frontend/

# 5. 人工把 frontend/README.md.original 的內容合併進新產生的 frontend/README.md，
#    確認合併後再刪除備份
rm frontend/README.md.original

# 6. 清掉暫存資料夾
rm -rf <scratchpad>/frontend_scaffold_staging

# 7. 驗證：確認 frontend/ 底下的新檔案有被 git 認出是新增，且沒有動到其他任何檔案
git status
```

**關鍵安全屬性**：第 1–2 步完全不碰 `frontend/`；第 3 步只是改檔名（歷史可追溯），不是刪除；只有第 4 步才第一次真正寫入 `frontend/`，且是明確的複製動作，不是工具自己決定要不要覆寫。

---

## 8. 預計資料夾與 Component 架構

```text
frontend/
  app/
    layout.tsx              # root layout：組裝 Sidebar + TopNav + main content 外框
    page.tsx                # "/" → redirect 到 /overview
    overview/page.tsx
    overview/loading.tsx
    overview/error.tsx
    datasets/page.tsx
    datasets/loading.tsx
    datasets/error.tsx
    documents/page.tsx
    analysis/page.tsx
    assistant/page.tsx       # placeholder
    globals.css
  components/
    layout/
      Sidebar.tsx            # Client Component
      TopNav.tsx
      PageShell.tsx
    ui/
      EmptyState.tsx
      Card.tsx
  lib/
    api/
      client.ts              # server-only typed fetch wrapper，讀 API_BASE_URL
      types.ts                # 對應 backend Pydantic schema 的 TS interface
  public/
  .env.local.example
  next.config.ts
  tsconfig.json
  package.json
  README.md                  # 更新，修正 Step 編號，合併原內容
```

分層原則：`app/*/page.tsx` 保持薄（呼叫 `lib/api` 拿資料、決定 loading/error/empty、組裝元件），畫面骨架獨立在 `components/layout`，可重用小元件在 `components/ui`，API 呼叫邏輯與型別集中在 `lib/`——呼應 backend 既有「main.py 保持薄，邏輯拆到 `*_queries.py`」慣例。

---

## 9. 五個基礎頁面的範圍

| 頁面 | 本 Step 內容 |
|---|---|
| Overview | 顯示 backend 連線狀態卡片（打 `/health`/`/version`），不畫任何圖表 |
| Datasets | 打 `GET /datasets`，表格呈現，loading/error/empty 三態齊全 |
| Documents | Placeholder，明確顯示「尚未開放（等待 Step 10 RAG 正式整合）」，不偽造資料 |
| Analysis | Placeholder，顯示「尚未開放（等待 Step 9 Rule-Based Analysis）」 |
| AI Assistant | Placeholder，純 UI 殼，無 chat 邏輯（等待 Step 12） |

---

## 10. Step 7 與 Step 8 的邊界

**Step 7 完成時的紅線：不安裝任何繪圖套件（Recharts/Chart.js/…），Overview 頁只能用文字/卡片/表格呈現真實資料**，不畫任何 PV/SOC/電價曲線圖。Step 8 才會另外討論繪圖套件選型（需另外詢問同意），並實作 `docs/DEVELOPMENT_WORKFLOW.md` 第 234–249 行列出的 8 種固定圖表，聚焦 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 場景。

---

## 11. 分段 Implementation Plan 與每段驗收點

| 段落 | 內容 | 驗收點 |
|---|---|---|
| A. 安全初始化 | 第 7 節的 command sequence | `git status` 顯示 `frontend/README.md` 被 modified（非 deleted）、其餘為新增檔案；`frontend/.git` 不存在（確認沒有巢狀 repo）；`frontend/CLAUDE.md`/`AGENTS.md` 不存在（確認 `--no-agents-md` 生效） |
| B. 骨架與 layout | `layout.tsx`、`Sidebar`、`TopNav`、`PageShell` | `npm run dev` 啟動無錯誤；5 個路由都能訪問且顯示對應 Sidebar 項目；縮小視窗寬度能看到 Sidebar 收合 |
| C. Overview 串接 | `app/overview/page.tsx` 直接 fetch `/health`/`/version` | backend 有跑時顯示「已連線」＋版本號；把 backend 關掉重整頁面，`error.tsx` 正確顯示錯誤畫面而不是白屏 |
| D. Datasets 串接 | `app/datasets/page.tsx` 直接 fetch `/datasets` | DB 有 dataset 時顯示表格；DB 沒資料時顯示 `EmptyState`；backend 關掉時顯示 `error.tsx` |
| E. Placeholder 頁面 | Documents/Analysis/Assistant | 三頁都能訪問，明確文字說明「尚未開放，等待 Step 幾」，不偽造假資料 |
| F. 文件與收尾 | 更新 `frontend/README.md`、跑 `npm run build`/`npm run lint` | build 成功、lint 無錯誤；過一遍第 12 節的手動驗收清單 |

每段完成後可先給使用者看再進下一段，不需要一次做完整個 Step 7 才回報。

---

## 12. 測試、Lint、Type Check、Build 與手動驗收標準

- **Lint**：沿用 `create-next-app` 官方預設 ESLint config，不額外加自訂規則。
- **Type check**：`tsc --noEmit`（Next.js build 本身也會做型別檢查）。
- **Build**：`npm run build` 必須成功，作為 Step 7 驗收標準之一。
- **自動化測試**：**本輪不引入**（Jest/Vitest/Playwright 皆不裝）——Step 7 骨架變動快，測試投資報酬率低，建議等 Step 8 頁面內容穩定後再評估。
- **手動驗收清單**：
  1. `npm run dev` 可啟動且無錯誤
  2. 5 個頁面路由都能訪問、非 404
  3. Sidebar/TopNav 桌面與手機寬度都正常顯示與收合
  4. Datasets 頁在「backend 有資料／無資料／backend 未啟動」三種情況下分別正確顯示資料／empty／error
  5. `npm run build` 成功
  6. `npm run lint` 無新增錯誤

---

## 13. 風險與 Rollback Plan

**風險**：
1. Next.js/React 版本與部分套件相容性問題——用官方 `create-next-app` 預設版本組合，不手動兜版本，降低風險。
2. scaffold 產生的 `package.json` 可能用 caret range（例如 `"next": "^16.2.10"`）而非精確 pin——實作完成後需要檢查並視情況拿掉 `^` 以利可重現性，這件事無法在規劃階段確定，需等實際跑過才知道。
3. `--agents-md` 忘記關閉會產生第二份 `CLAUDE.md`，`--disable-git` 忘記加會產生巢狀 git repo——已在第 7 節的 command 中明確標注這兩個旗標，避免實作時漏掉。
4. `frontend/README.md` 的舊 Step 編號（目前寫「等待 Step 6: Frontend Foundation」，roadmap 重排後應為 Step 7）若不修正，未來容易造成混淆——已列入第 11 節段落 F 的收尾工作。
5. 過早導入 UI library／圖表套件的誘惑——已用第 3、10 節的明確邊界防範。

**Rollback plan**：`frontend/` 是既有資料夾但目前只有一個 README，實作階段的變更集中在新增檔案，本身不影響 `backend/`/`database/`/Docker 既有功能。建議 Step 7 完成後獨立成一個 commit，不與其他 Step 混在一起；若方向需要調整，可以直接 `git revert` 該次 commit 或刪除 `frontend/` 內新建檔案重來，不影響任何已提交的歷史。

---

## 14. 文件狀態

**此文件是已核准的 planning，尚未開始實作。** 對應決策討論已在對話中與使用者逐項確認（Next.js exact version、API connection 方案、安全初始化流程）。實作只能在使用者另外明確核准後才可開始，依序包含：`npx create-next-app` 執行、`frontend/` 目錄的任何寫入、`backend/app/main.py` 相關檢查（本計畫已確認不需要修改）。本文件本身的保存不構成實作核准。
