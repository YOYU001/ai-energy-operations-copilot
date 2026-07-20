# frontend

AI Energy Operations Copilot 的前端（Next.js App Router + TypeScript + Tailwind CSS），對應 `docs/STEP7_FRONTEND_PLAN.md` 的 Step 7 Frontend Foundation。目前僅建立骨架與 5 個基礎頁面（Overview / Datasets / Documents / Analysis / Assistant），尚未安裝圖表套件（Chart.js/Recharts 等留給後續 Step 評估）。

## 啟動開發環境

**1. 設定環境變數**

macOS/Linux：
```bash
cp .env.local.example .env.local
```

Windows（PowerShell）：
```powershell
Copy-Item .env.local.example .env.local
```

`.env.local` 內的 `API_BASE_URL` 預設指向本機 FastAPI backend（`http://localhost:8000`），需搭配 `docker compose up -d` 啟動的資料庫與 `uvicorn app.main:app --reload --app-dir backend` 一起使用（見根目錄 `CLAUDE.md`）。

**2. 安裝套件（使用 `npm ci`，不要用 `npm install`）**
```bash
npm ci
```
本專案已提交 `package-lock.json`，`npm ci` 會依 lock file 精確安裝，確保環境可重現；`npm install` 可能依 caret range（`^`）解析出不同的次版本。

**3. 啟動 dev server**
```bash
npm run dev
```
開啟 [http://localhost:3000](http://localhost:3000)。

## API 串接方式

所有對 FastAPI backend 的請求都走 `lib/api/client.ts`，這是**唯一**呼叫 backend 的入口（頁面元件不直接 `fetch`）。目前頁面（`app/overview/page.tsx`、`app/datasets/page.tsx`）都是 Server Component，在 Next.js 的 server side 直接呼叫 FastAPI，完全不經過瀏覽器，因此不受 CORS 規則管轄，backend 也不需要加 `CORSMiddleware`。

**`API_BASE_URL` 只能在 server-side 使用，不要改成 `NEXT_PUBLIC_API_BASE_URL`**：加上 `NEXT_PUBLIC_` 前綴會讓這個網址被打包進瀏覽器端的 JS bundle，但目前架構下瀏覽器完全不需要知道 backend 網址。若未來引入 Route Handler proxy 或 client-side fetch（例如 AI Assistant 即時對話），才需要重新評估。

## 套件版本策略

`next`、`react`、`react-dom`、`eslint-config-next` 已在 `package.json` 精確 pin（無 `^`）；其餘 devDependencies（Tailwind、TypeScript、`@types/*`、eslint）維持 `create-next-app` 預設的 caret range。這是刻意決定，不在本輪擴大修改：`package-lock.json` 已鎖定所有套件的實際版本，正式環境重建一律用 `npm ci`，caret range 只影響「有人手動跑 `npm install` 更新」時的上限，不影響可重現性。

## 資料夾結構

```
app/            App Router 頁面（overview / datasets / documents / analysis / assistant）
components/
  layout/       AppShell、Sidebar（Client Component，唯一需要瀏覽器 state 的地方）、TopNav、PageShell
  ui/           EmptyState 等純展示型元件
lib/
  api/          client.ts（fetch 邏輯）+ types.ts（API response 型別定義）
```

## Lint / Build

```bash
npm run lint
npm run build
```
