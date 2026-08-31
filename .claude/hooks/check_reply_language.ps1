# Stop hook（每輪 assistant 回覆結束時觸發）。
#
# 依 CLAUDE.md 的「回覆語言規則」：對使用者的回覆一律使用繁體中文，除非遇到
# 專有名詞、程式碼、檔名、指令、API/函式名稱等技術術語才用英文。這條規則已
# 違反多次（見 memory: feedback_traditional_chinese_replies.md），因此改用
# hook 在每輪結束時實際檢查最後一則 assistant 文字回覆，語言比例不符就用
# decision: block 要求重寫，而不是只靠 CLAUDE.md/memory 提醒。
#
# 設計取捨（比照 check_md_language.ps1 的既有慣例）：
#   - 判斷前先排除 code block（```...```）、inline code（`...`）、URL，這些
#     本來就該保持英文，不排除會不公平地拉低中文比例。
#   - 門檻沿用 check_md_language.ps1 的 15%（中文字元佔比低於 15% 才擋），
#     維持全專案一致的寬鬆標準，避免正常混用技術術語的回覆被誤判。
#   - 最小有意義字元門檻設 40（比 markdown Edit 的 20 高一些，因為聊天回覆
#     常包含大量檔名/指令/SHA 等本來就該是英文的片段，太低的門檻容易對極短
#     回覆做出不可靠的判斷）。
#   - 必須檢查 stop_hook_active：Claude Code 在「這次 Stop 本身就是被前一次
#     block 觸發後重新產生的回覆」時會把這個欄位設為 true，此時不可再次
#     block，否則會卡成無窮迴圈。
#   - 只看最後一則 assistant 訊息裡的 text content block，不含 thinking
#     block（那是內部思考過程，不是實際顯示給使用者的回覆）。

$ErrorActionPreference = "SilentlyContinue"

[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
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

if ($payload.stop_hook_active -eq $true) {
    Write-Output '{}'
    exit 0
}

$transcriptPath = $payload.transcript_path
if ([string]::IsNullOrWhiteSpace($transcriptPath) -or -not (Test-Path $transcriptPath)) {
    Write-Output '{}'
    exit 0
}

$lines = Get-Content -Path $transcriptPath -Encoding UTF8
$lastAssistantText = $null

for ($i = $lines.Count - 1; $i -ge 0; $i--) {
    $line = $lines[$i]
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    try {
        $entry = $line | ConvertFrom-Json
    } catch {
        continue
    }
    if ($entry.type -eq "assistant" -and $entry.message.role -eq "assistant") {
        $textParts = @()
        foreach ($block in $entry.message.content) {
            if ($block.type -eq "text" -and -not [string]::IsNullOrWhiteSpace($block.text)) {
                $textParts += $block.text
            }
        }
        if ($textParts.Count -gt 0) {
            $lastAssistantText = ($textParts -join "`n")
            break
        }
        # 這則 assistant 訊息只有 tool_use（沒有文字回覆），繼續往前找
    }
}

if ([string]::IsNullOrWhiteSpace($lastAssistantText)) {
    Write-Output '{}'
    exit 0
}

$stripped = $lastAssistantText -replace '(?s)```.*?```', ''
$stripped = $stripped -replace '`[^`]*`', ''
$stripped = $stripped -replace 'https?://\S+', ''

$meaningfulChars = ($stripped -replace '\s', '')
$totalCount = $meaningfulChars.Length

if ($totalCount -lt 40) {
    Write-Output '{}'
    exit 0
}

$cjkMatches = [regex]::Matches($stripped, '[一-鿿]')
$cjkCount = $cjkMatches.Count
$ratio = $cjkCount / $totalCount

if ($ratio -lt 0.15) {
    $percent = [math]::Round($ratio * 100, 0)
    $reason = "你剛才這則回覆看起來大部分是英文（排除 code block/inline code/URL 後，中文字元佔比約 ${percent}%）。" +
              "依 CLAUDE.md 的「回覆語言規則」，對使用者的回覆一律要用繁體中文，只有專有名詞、程式碼、檔名、指令、" +
              "API/函式名稱等技術術語才保留英文。請把這則回覆改寫成繁體中文再重新輸出。"
    $result = @{
        decision = "block"
        reason   = $reason
    }
    Write-Output ($result | ConvertTo-Json -Compress -Depth 5)
    exit 0
}

Write-Output '{}'
exit 0
