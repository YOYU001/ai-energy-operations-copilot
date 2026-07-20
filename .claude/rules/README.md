# .claude/rules/

這個資料夾放的是「模組化的規則檔案」，透過 Claude Code 的 `@` import 語法（例如 `@.claude/rules/code-style.md`）被引用進 `CLAUDE.md`，讓 `CLAUDE.md` 本身可以保持精簡，細節規則拆到各自獨立的檔案裡。

## 目前狀態

已建立兩份規則檔案，並在 `CLAUDE.md` 的「模組化規則」章節掛上 `@` import：

- `code-style.md`——Python 程式碼風格，核心原則是效率優先（避免重複計算、N+1 查詢等），不是行數最短；依 `backend/app/` 實際程式碼歸納既有慣例（type hint、docstring 只寫 WHY、Pydantic schema、import 順序）。
- `frontend/react.md`——React/Next.js 慣例。產品定位是 `/assistant` 頁面要做到接近 ChatGPT 的介面與體驗，但資料來源預設走 Internal Knowledge Only；外部搜尋切換目前只做 UI 佔位，功能保持關閉（若要轉正需先在 `CLAUDE.md` 走範圍變更流程）。同時依 `frontend/` 實際程式碼歸納既有慣例（Server Component 為預設、`lib/api/` 為唯一 API 入口、runtime type guard、`@/*` alias 等）。

## 新增規則檔案時的注意事項

規則內容應該根基於專案真正做過的決策或使用者明確給的規則，不要為了填滿檔案而編造慣例。如果某個主題還沒有足夠的既有做法或明確規則可以歸納，就先不建立對應檔案，等真的有了再補。

任何一個檔案建好之後，都必須在 `CLAUDE.md` 裡加上對應的 `@.claude/rules/<file>.md` import 那一行，這個規則才會真正生效——單純放在這個資料夾裡但沒有被引用的檔案，不會有任何作用。
