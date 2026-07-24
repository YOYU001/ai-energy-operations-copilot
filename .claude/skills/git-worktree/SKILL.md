---
name: git-worktree
description: 這個專案「用 GitHub 開發一個功能」的完整流程都走這個 skill——開獨立 worktree/branch、實作、lint/build、commit、push、開 PR、code review（自己 + 彙整外部工具如 Codex 的意見）、回覆 comment、merge、清理。使用者以後只要說「幫我開一個新功能」「push 上去」「開 PR」「review 這個 PR」「merge」這類話，都應該觸發這個 skill，不需要每次重新解釋流程。管理多個本機 git worktree（同一個 .git repo 同時掛接好幾個獨立工作目錄，各自 checkout 不同 branch，不用 stash/checkout 就能同時開發多條分支），並在要清掉一個 branch 時，於刪除 GitHub 上的 remote branch 之前先做 review、一定要問過使用者才會動手。用法："/git-worktree add <branch名稱> [--from <base branch>] [--push]"、"/git-worktree list"、"/git-worktree remove <branch名稱>"、"/git-worktree lint-build"、"/git-worktree pr-comment <PR> <path> <line> <內容>"、"/git-worktree pr-reply <comment_id> <內容>"、"/git-worktree pr-merge <PR> [--strategy squash|merge]"。remove 前一定會先檢查有沒有未 commit 的修改，有的話會拒絕並列出來，不會自動用 --force 硬砍；remote branch 一律要先 review、問過使用者才能刪；merge 前一定要使用者明確同意。
---

執行 `python .claude/skills/git-worktree/scripts/worktree_manager.py <子指令>`（從 repo 根目錄執行，需要在 `AI_Copilot` conda 環境中）。

## 最重要的規則：刪 GitHub 上的 remote branch 之前，一定要先問過使用者

這條規則沒有例外，也不是靠參數控制，是每次執行都要遵守的行為：

1. `remove <branch>` 只處理本機（worktree + 本機 branch）。如果移除後發現這個 branch 還有 remote 對應（`origin/<branch>` 還在），script 只會印一個提示，**不會**自動去動 remote，也不會自動接著跑 `review` 或 `delete-remote`。
2. 使用者想清掉一個還留在 GitHub 上的 branch 時，你（Claude）要先跑 `review <branch>`，這個子指令純讀取、不會刪任何東西，會回報：這個 branch 是否已經完全合併進 `main`、還沒進 main 的 commit 有哪些、跟 main 的 diff stat 長怎樣。
3. 根據 `review` 的結果分兩種情境回報給使用者，**都要停下來等使用者回答**，不能自己判斷後就動手：
   - **已經完全合併進 main**：簡短回報「這條 branch 完成了 XXX（從 commit 訊息摘要），已經合併進 main 了」，問使用者要不要刪除 remote branch。
   - **還沒合併、有獨立內容**（例如用 worktree 讓 subagent 在裡面獨立工作、做完要決定收不收的情境）：完整整理這個 branch 改了什麼（讀 `review` 印出的 commit log 跟 diff stat，必要時自己額外跑 `git diff main...<branch>` 看實際內容），給出你的審查意見（正確性問題、可以怎麼簡化、你的疑問），並給建議（可以直接合併 / 需要修改 / 你自己看看），然後問使用者要**合併進 main**、**刪除不合併**、**先不動**、還是有其他意見。
4. 只有在使用者於**當下這個對話輪次**明確回答「要刪」之後，才能執行 `delete-remote <branch>`。不能把這次同意當成之後也自動適用，每一次都要重新問。

## 子指令

**`add <branch名稱> [--from <base>] [--push]`**
1. 檢查目標路徑（`../<repo資料夾名稱>-worktrees/<branch名稱>`）是否已被佔用、branch 名稱是否已存在，避免蓋掉東西。
2. `git worktree add -b <branch名稱> <路徑> [<base>]` 建立新 worktree + 新 branch（`--from` 沒指定就從目前 HEAD 分出去）。
3. 若加了 `--push`，建立成功後在新 worktree 裡執行 `git push -u origin <branch名稱>`，設定 upstream tracking。push 失敗不會復原已建立的本機 worktree，只會分開回報「本機建立成功，push 失敗」。

**`list`**
列出目前所有 worktree（路徑、branch），並對每一個實際跑 `git status --porcelain` 標示 clean 還是 dirty（有未 commit 修改）——不是單純列路徑，決定要不要 `remove` 前可以直接看這個結果。

**`remove <branch名稱>`**
1. 先找到該 branch 對應的 worktree 路徑，若目標是主要工作目錄（你平常在用的那個），直接拒絕。
2. 實際跑 `git status --porcelain` 確認乾淨，**有任何未 commit 的修改就拒絕移除**，把髒污的檔案列出來，並提示使用者自己 commit/stash，或自己手動加 `--force` 執行——這個 script 不會自動幫你用 `--force`。
3. 確認乾淨後才 `git worktree remove <路徑>`，成功後再嘗試 `git branch -d <branch名稱>`（安全刪除，只有已合併的 branch 才會成功；沒合併會保留 branch 並提示，不會用 `-D` 強制刪除）。
4. 若這個 branch 還有 remote 對應，只會印一行提示，不會做任何後續動作——要處理 remote 一律照上面「最重要的規則」那節走。

**`review <branch名稱>`**（純讀取，不會刪或改任何東西）
回報：`origin/<branch>` 是否存在、是否已完全合併進 `main`（`git merge-base --is-ancestor`）。已合併的話印出這個 branch 最近的 commit 當摘要素材；沒合併的話印出 `git log main...<branch>`（還沒進 main 的 commit）跟 `git diff main...<branch> --stat`（改了哪些檔案），給你彙整審查意見用。

**`delete-remote <branch名稱>`**（純機械操作，不做任何判斷或詢問）
直接執行 `git push origin --delete <branch名稱>`。這個子指令本身不會問使用者任何問題——**呼叫這個子指令之前，你必須已經照上面「最重要的規則」那節走完 review + 詢問使用者的流程，並得到當下明確同意**，這個規則寫在 SKILL.md 這一層，script 本身無法強制執行，完全靠你自己遵守。

**`lint-build [--dir <子目錄，預設 frontend>]`**
在指定子目錄依序跑 `npm run lint` 再 `npm run build`，任一個失敗就停下回報，不會自己嘗試修。純粹的通過/失敗檢查，不做任何判斷。

**`pr-comment <PR編號> <檔案路徑> <行號> <內容>`**
在指定 PR 目前的 head commit 上貼一則 inline review comment（自動抓 head SHA，不用你自己查）。純機械貼文字，**貼什麼內容、要不要貼是你（Claude）的判斷**，這個子指令不篩選、不過濾。

**`pr-reply <comment_id> <內容>`**
在既有的 review comment 討論串下面回覆（不是開新的獨立留言）。同樣純機械操作，回覆內容由你決定。

**`pr-merge <PR編號> [--strategy squash|merge]`**（預設 squash）
執行 `gh pr merge --squash|--merge`。**只負責合併，不會刪 branch**（不管本機還是 remote）——刻意不用 `gh` 的 `--delete-branch`：一來它會嘗試刪本機 branch，如果本機還有 worktree 佔用著（剛做完事、還沒 `remove` 的正常狀態）就會直接失敗；二來它刪 remote branch 不會經過這個 skill 的 review 安全檢查。合併完之後，照下面完整流程的第 12 步，另外跑 `remove`（本機）+ `review`/`delete-remote`（remote）。**這個子指令跟 `delete-remote` 一樣，不會問使用者任何問題——執行前你必須已經在這個對話輪次裡得到使用者明確同意要 merge**，不能拿之前哪一輪的同意當這次的許可。

若指令回傳非 0 exit code，代表有檢查沒過或操作失敗，把印出來的訊息完整回報給使用者，不要自己判斷「應該是成功了」。

## 完整功能開發流程（使用者說「幫我開發／push／開PR／review／merge」時照這個走）

這是需要判斷的部分，寫在這裡給你（Claude）當檢查清單，不是寫進 script——因為每一步「要不要繼續、內容是什麼」都需要你當下判斷，不能寫死：

1. **確認 branch 名稱**（英文、`feature/xxx` 慣例），跑 `add <branch> --push` 開獨立 worktree。
2. **實作功能**——用一般的 Edit/Write 工具，這不屬於這個 skill 管，是你平常的開發工作。
3. **跑 `lint-build`**，沒過就回頭修，不要帶著失敗的 lint/build 往下走。
4. **自己決定要不要 commit、怎麼分批、commit 訊息怎麼寫**——維持小步驟、訊息講清楚做了什麼跟為什麼，這是你的判斷，不是機械化步驟。
5. **`add` 時已經 `--push` 過的話直接 `git push`**；開 PR 用 `gh pr create`（標題/內文你自己寫，需要包含 summary 跟 test plan）。
6. **開完 PR 明確告訴使用者**，如果他們有自己的外部工具（例如 Codex）要 review，先停下來等他們看過/處理完，不要自己往下衝。
7. **自己對這個 PR 做 code review**（可以用多角度分析，比照這個專案已經驗證過的方式：抓 diff、分幾個角度找問題、驗證候選發現、只保留可信的）。**先把發現整理好列給使用者看，不要直接呼叫 `pr-comment` 貼出去**——這條沒有例外，不管你判斷得多清楚、多有把握，都要先讓使用者看過。
8. **如果使用者也有外部 review 工具的意見（例如 Codex）**，把兩邊的發現彙整起來一起呈現：你對每一項的判斷（該修/不該修/有疑義）跟理由，全部列給使用者看。
9. **等使用者針對每一項回覆「沒問題」或給出他的決定之後，才用 `pr-comment` 把最終版本貼上去**——內容可以是你原本準備的版本，也可能因為使用者的意見而調整過，總之貼之前要先經過使用者確認。**使用者的語言慣好用什麼語言，comment 就用什麼語言**（這個專案預設繁體中文）。
10. **需要修改的部分**：改完、重新跑 `lint-build`、commit、push（PR 會自動更新）。**回覆討論串（`pr-reply`）也適用同一條規則**——先把要回覆的內容給使用者看過、確認沒問題，才用 `pr-reply` 送出，不要自己判斷完就直接回覆。
11. **問使用者要不要 merge、用哪種 merge 方式**（這個專案預設 squash），得到明確同意後才跑 `pr-merge <PR> --strategy squash`——這一步只會合併，不會刪任何 branch。
12. **確認清理乾淨（兩個獨立步驟，`pr-merge` 都不會幫你做）**：先跑 `remove <branch>` 清本機 worktree（此時應該已經合併，會順利通過乾淨檢查）；再跑 `review <branch>` 確認 remote 狀態、問使用者同意後跑 `delete-remote <branch>` 清 GitHub 上的 remote branch。

## Dependabot PR 的審查方式

`dependabot.yml` 本身沒有限制更新幅度——修補、次版本、主版本升級都會照樣自動開 PR，這是刻意的：**開 PR 這件事本身就是最直接的通知**，不需要另外蓋一套通知機制。差別在於你（Claude）審查這種 PR 的方式，要分兩種情境：

1. **先判斷是不是主版本升級（major version）**：Dependabot 的 PR 標題通常會寫「Bump `<套件>` from `X.Y.Z` to `A.B.C`」，比較 `X` 跟 `A` 這兩個數字——不一樣就是主版本升級（例如 `1.x` → `2.x`）；`X` 相同、只有 `Y`/`Z` 變的，是次版本／修補版本。
2. **修補／次版本**：照一般 PR 流程走就好（確認 CI 過、問使用者要不要 merge），不用額外深入調查，這種按 semver 慣例通常不會破壞相容性。
3. **主版本升級**：**不要直接照一般流程處理**。先去查這個套件的 release notes／changelog（可以用 WebSearch/WebFetch，或看套件的 GitHub repo），整理出：這次升級大概動到什麼地方、有沒有已知的 breaking change、對這個專案目前的用法有沒有實際影響。整理完給使用者一個明確建議（現在適合升級 / 建議先觀望 / 有具體風險要注意），然後才問使用者要不要 merge——決定權還是在使用者，你只負責調查跟給建議，不能自己判斷「看起來沒問題」就直接處理掉。

## 已知限制 / 之後可以優化的地方（記錄用，先不動手）

這兩點是 2026-07-23 建完整套流程後盤點出來的真實缺口，不是憑空想像的——但故意先不修，等真的被撞到、有具體情境可以驗證怎麼做才對時再回來補，避免對還沒發生的需求做過度設計：

1. **`lint-build` 只涵蓋前端**：只會跑 `npm run lint`/`npm run build`，沒有對應的 `pytest` 檢查。等第一次有 PR 改到 `backend/app/` 時（`CLAUDE.md` 要求 pytest 全過），要幫這個 skill 補一個等效的後端檢查子指令。
2. **Code review 的角度覆蓋範圍還沒固化**：目前「怎麼分角度找問題、要不要驗證、要跑幾個角度」都是當下臨場判斷，同一個 PR 給不同狀態的 Claude 審，覆蓋範圍可能不一致。等實際跑過多次、觀察出「哪種角度組合最划算」之後，再把它寫成這裡的固定檢查清單。
