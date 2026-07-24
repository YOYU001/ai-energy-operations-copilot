# PreToolUse hook for the Bash tool.
#
# Blocks python invocations that don't reference the AI_Copilot conda
# environment, per CLAUDE.md's "Python Environment Rules" (all Python work
# must happen in AI_Copilot, never base or a global interpreter).
#
# Why check the command TEXT instead of $env:CONDA_DEFAULT_ENV: each Bash
# tool call starts a fresh shell with no persisted "conda activate" state
# (shell state does not carry over between Bash calls), and this hook is a
# separate process from that shell anyway -- its own environment reflects
# whatever Claude Code itself was launched in, not the upcoming command's
# environment. Checking whether the command string itself activates or
# targets AI_Copilot is the only signal that is actually reliable here.

$ErrorActionPreference = "SilentlyContinue"

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

$cmd = $payload.tool_input.command
if ([string]::IsNullOrWhiteSpace($cmd)) {
    Write-Output '{}'
    exit 0
}

# Heredoc bodies (e.g. `git commit -m "$(cat <<'EOF' ... EOF)"`) are inert
# text data, never executed -- but the word "python" legitimately shows up
# in prose there (e.g. a commit message describing a CodeQL language list).
# Strip heredoc bodies before matching so that doesn't false-positive; this
# never hides a real invocation, since the invoking token (if any) appears
# before the `<<`, outside the stripped body.
$cmdForMatching = [regex]::Replace($cmd, "(?s)<<-?\s*[`'`"]?(\w+)[`'`"]?.*?\r?\n\s*\1\b", "")

# Same idea for known flags whose value is always inert prose, never
# executed, on the specific tools this project actually uses (git, gh) --
# e.g. `gh pr create --title "...python..."` describing what a fix does.
# This is a maintained allowlist, not a general solution: a flag/tool not
# listed here that happens to mention "python" in a plain quoted argument
# (not a heredoc) will still false-positive. Add to this list as new cases
# are found rather than trying to fully parse shell syntax -- knowing
# whether an arbitrary command's argument is data or executable requires
# understanding that command's semantics, which a regex cannot do in general.
$dataFlagPattern = "(?:-m|-F|--title|--body|--body-file)\s+(?:`"(?:[^`"\\]|\\.)*`"|'(?:[^'\\]|\\.)*')"
$cmdForMatching = [regex]::Replace($cmdForMatching, $dataFlagPattern, "")
$cmdForMatching = [regex]::Replace($cmdForMatching, "-f\s+body=(?:`"(?:[^`"\\]|\\.)*`"|'(?:[^'\\]|\\.)*')", "")

# Only care about commands that actually invoke a "python"/"python3" binary,
# not e.g. a filename that happens to contain "python" as a substring.
$invokesPython = $cmdForMatching -match '(^|[^A-Za-z0-9_])python3?([^A-Za-z0-9_]|$)'

if ($invokesPython) {
    # Harmless, environment-independent invocations are exempt.
    $isHarmless = $cmd -match '--version|--help|(^|[^A-Za-z0-9_])-V([^A-Za-z0-9_]|$)'

    if (-not $isHarmless) {
        $referencesEnv = $cmd -match 'AI_Copilot'

        if (-not $referencesEnv) {
            $reason = "This command invokes python but does not reference the AI_Copilot conda environment. " +
                      "Per CLAUDE.md, all Python work must run in AI_Copilot. Prefix the command with: " +
                      "source /c/Users/User/anaconda3/etc/profile.d/conda.sh && conda activate AI_Copilot && <your command> " +
                      "(or call the AI_Copilot env's python.exe directly), then retry."
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
    }
}

Write-Output '{}'
exit 0
