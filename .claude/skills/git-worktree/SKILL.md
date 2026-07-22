---
name: git-worktree
description: 管理多個本機 git worktree（同一個 .git repo 同時掛接好幾個獨立工作目錄，各自 checkout 不同 branch，不用 stash/checkout 就能同時開發多條分支），並在要清掉一個 branch 時，於刪除 GitHub 上的 remote branch 之前先做 review、一定要問過使用者才會動手。用法："/git-worktree add <branch名稱> [--from <base branch>] [--push]"、"/git-worktree list"、"/git-worktree remove <branch名稱>"。remove 前一定會先檢查有沒有未 commit 的修改，有的話會拒絕並列出來，不會自動用 --force 硬砍；remote branch 一律要先 review、問過使用者才能刪。
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

若指令回傳非 0 exit code，代表有檢查沒過或操作失敗，把印出來的訊息完整回報給使用者，不要自己判斷「應該是成功了」。
