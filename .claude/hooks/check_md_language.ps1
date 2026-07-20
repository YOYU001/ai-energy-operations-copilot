# Write / Edit 工具的 PreToolUse hook。
#
# 依 CLAUDE.md 的「回覆語言規則」：markdown 內容預設要用繁體中文，只有專有名詞
# 或特殊術語才保留英文。這支 hook 會擋下「新建立」的 .md 檔案（Write）以及
# 「對既有 .md 檔案的增量修改」（Edit），如果內文看起來絕大部分是英文，就拒絕寫入。
#
# 設計取捨：
#   - Write 比對整份 content；Edit 比對 new_string（新增/修改的那段文字），
#     不看 old_string（那是被取代掉的舊內容，跟這次寫入無關）。
#   - 判斷前會先排除 code block（``` 包起來的）、inline code（` 包起來的）、
#     以及 URL——這些本來就該保持英文，不排除的話會不公平地拉低中文比例。
#   - Write 的最小有意義字元門檻是 60（整份檔案太短不足以判斷）；Edit 片段
#     通常只有一兩行，門檻降到 20，避免像 PROGRESS.md 那種單行英文摘要因為
#     長度不足而被直接放行、形同沒檢查。
#   - 門檻刻意設得寬鬆（中文字元佔比低於 15% 才會擋），避免正常混用技術術語
#     的文件被誤判。
#   - 只檢查「這個 repo 底下」的 .md 檔案。Claude Code 的 auto-memory 系統會寫
#     到 repo 之外的 ~/.claude/projects/<hash>/memory/，那些檔案照慣例本來就
#     是英文（例如既有的 feedback_dev_server_kill.md），不歸這條語言規則管，
#     曾經因為沒排除而被誤擋（實測發現，不是假設）。

$ErrorActionPreference = "SilentlyContinue"

# 明確指定 stdin 用 UTF-8 讀取：子行程預設會用系統的 ANSI/OEM 編碼讀取管道
# 輸入，不是 UTF-8，若不指定，piped 進來的中文內容在這一步就會先亂碼，
# 導致後面的中文字元比例判斷永遠算出 0%（這是實測抓到的真實 bug，不是假設）。
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$rawInput = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($rawInput)) {
    Write-Output '{}'
    exit 0
}

try {
    $payload = $rawInput | ConvertFrom-Json
} catch {
    Write-Output '{}'
    exit 0
}

$toolName = $payload.tool_name
$filePath = $payload.tool_input.file_path

if ($toolName -eq "Edit") {
    $content = $payload.tool_input.new_string
    $minMeaningfulChars = 20
} else {
    $content = $payload.tool_input.content
    $minMeaningfulChars = 60
}

if ([string]::IsNullOrWhiteSpace($filePath) -or [string]::IsNullOrWhiteSpace($content)) {
    Write-Output '{}'
    exit 0
}

if ($filePath -notmatch '\.md$') {
    Write-Output '{}'
    exit 0
}

# 只管 repo 底下的檔案；repo 外的路徑（例如 auto-memory 的
# ~/.claude/projects/<hash>/memory/）一律放行。
$projectRoot = (Get-Location).Path
try {
    $resolvedPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $filePath))
} catch {
    Write-Output '{}'
    exit 0
}
$projectRootWithSep = $projectRoot.TrimEnd('\') + '\'
if (-not $resolvedPath.StartsWith($projectRootWithSep, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Output '{}'
    exit 0
}

# 判斷語言比例前，先排除 code block、inline code、URL。
$stripped = $content -replace '(?s)```.*?```', ''
$stripped = $stripped -replace '`[^`]*`', ''
$stripped = $stripped -replace 'https?://\S+', ''

$meaningfulChars = ($stripped -replace '\s', '')
$totalCount = $meaningfulChars.Length

if ($totalCount -lt $minMeaningfulChars) {
    Write-Output '{}'
    exit 0
}

$cjkMatches = [regex]::Matches($stripped, '[一-鿿]')
$cjkCount = $cjkMatches.Count
$ratio = $cjkCount / $totalCount

if ($ratio -lt 0.15) {
    $percent = [math]::Round($ratio * 100, 0)
    $reason = "這份 markdown 檔案的內文看起來大部分是英文（排除 code block/inline code/URL 後，中文字元佔比約 ${percent}%）。" +
              "依 CLAUDE.md 的「回覆語言規則」，markdown 內容預設要用繁體中文，只有專有名詞或特殊術語才保留英文。" +
              "請把內文改寫成繁體中文後再重試。"
    $result = @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = $reason
        }
    }
    Write-Output ($result | ConvertTo-Json -Compress -Depth 5)
    exit 0
}

Write-Output '{}'
exit 0
