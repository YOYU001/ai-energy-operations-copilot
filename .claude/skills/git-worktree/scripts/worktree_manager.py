"""git-worktree: manage multiple local working directories against this
repo's single .git history, so you can work on more than one branch at
once without stash/checkout gymnastics -- plus the mechanical, no-judgment
steps of shipping a feature through GitHub (lint/build, opening a PR,
posting/replying to review comments, merging).

Run from the project root:
    python .claude/skills/git-worktree/scripts/worktree_manager.py add <branch> [--from <base>] [--push]
    python .claude/skills/git-worktree/scripts/worktree_manager.py list
    python .claude/skills/git-worktree/scripts/worktree_manager.py remove <branch>
    python .claude/skills/git-worktree/scripts/worktree_manager.py review <branch>
    python .claude/skills/git-worktree/scripts/worktree_manager.py delete-remote <branch>
    python .claude/skills/git-worktree/scripts/worktree_manager.py lint-build [--dir frontend]
    python .claude/skills/git-worktree/scripts/worktree_manager.py pr-comment <pr> <path> <line> <body>
    python .claude/skills/git-worktree/scripts/worktree_manager.py pr-reply <comment_id> <body>
    python .claude/skills/git-worktree/scripts/worktree_manager.py pr-merge <pr> [--strategy squash|merge]

`review` and `delete-remote` are read/write-separated on purpose: `review`
only gathers facts (merged? commit log? diff stat?) and never touches
anything -- it exists so a human (via the calling agent) can decide what
to do with a remote branch before `delete-remote` is ever run. Deciding
and asking the user is the calling agent's job, not this script's.

The pr-* and lint-build commands are the same kind of split: they only do
the mechanical, deterministic part (run these exact commands, format this
exact API payload). Judgment calls -- whether to commit, whether a review
finding needs a code fix or just a reply, which PR comments to post, when
it's safe to merge -- stay with the calling agent, documented as a
checklist in SKILL.md, not hardcoded here.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Windows' console defaults stdout/stderr to the system codepage (cp950
# here), which crashes on the Unicode characters npm/eslint/Next.js print
# (checkmarks, arrows, box-drawing) -- force UTF-8 output regardless of
# codepage, replacing anything that still doesn't encode.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[4]
WORKTREES_ROOT = ROOT.parent / f"{ROOT.name}-worktrees"

# `gh` is often not on PATH in the same shell session that just installed it
# (see this project's own history -- PATH only refreshes on a fresh process).
# Fall back to the common Windows install location instead of failing outright.
GH_CMD = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"

# On Windows, `npm` is actually `npm.cmd`, which subprocess (without
# shell=True) can't resolve via CreateProcess the way a real shell would --
# resolving the full path through PATHEXT via shutil.which() sidesteps that.
NPM_CMD = shutil.which("npm") or "npm"


def _run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    # Windows defaults subprocess text decoding to the system codepage (cp950
    # here), which crashes on non-ASCII bytes npm/eslint/Next.js commonly
    # print (arrows, box-drawing characters, etc.) -- force UTF-8 and replace
    # anything that still doesn't decode instead of raising.
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def _gh(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return _run([GH_CMD, *args], cwd=cwd)


def _branch_exists(branch: str) -> bool:
    result = _run(["git", "branch", "--list", branch])
    return bool(result.stdout.strip())


def _remote_branch_exists(branch: str) -> bool:
    result = _run(["git", "ls-remote", "--heads", "origin", branch])
    return bool(result.stdout.strip())


def _list_worktrees() -> list[dict]:
    """Parse `git worktree list --porcelain` into one dict per worktree."""
    result = _run(["git", "worktree", "list", "--porcelain"])
    entries: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "branch":
            current["branch"] = value.replace("refs/heads/", "")
        elif key == "bare":
            current["branch"] = "(bare)"
    if current:
        entries.append(current)
    return entries


def cmd_add(branch: str, base: str | None, push: bool) -> int:
    target = WORKTREES_ROOT / branch
    if target.exists():
        print(f"[git-worktree] FAILED: target path already exists: {target}")
        return 1

    if _branch_exists(branch):
        print(f"[git-worktree] FAILED: branch '{branch}' already exists locally. "
              f"Use a different name, or run `git worktree add {target} {branch}` yourself "
              f"if you really want to check out the existing branch into a new worktree.")
        return 1

    add_cmd = ["git", "worktree", "add", "-b", branch, str(target)]
    if base:
        add_cmd.append(base)
    print(f"[git-worktree] creating worktree at {target} on new branch '{branch}'"
          f"{f' from {base}' if base else ''} ...")
    result = _run(add_cmd)
    if result.returncode != 0:
        print(f"[git-worktree] FAILED to create worktree:\n{result.stderr}")
        return 1
    print(result.stdout.strip() or f"[git-worktree] worktree created at {target}")

    if push:
        print(f"[git-worktree] pushing '{branch}' to origin ...")
        push_result = _run(["git", "push", "-u", "origin", branch], cwd=target)
        if push_result.returncode != 0:
            print(f"[git-worktree] worktree created locally, but push FAILED:\n{push_result.stderr}")
            return 1
        print(f"[git-worktree] pushed and tracking origin/{branch}.")

    print(f"\n[git-worktree] SUCCESS -- work in {target}")
    return 0


def cmd_list() -> int:
    worktrees = _list_worktrees()
    if not worktrees:
        print("[git-worktree] no worktrees found (unexpected -- even the main checkout should show up).")
        return 1

    for entry in worktrees:
        path = Path(entry["path"])
        branch = entry.get("branch", "(detached)")
        status_result = _run(["git", "status", "--porcelain"], cwd=path)
        dirty = bool(status_result.stdout.strip())
        state = "dirty (uncommitted changes)" if dirty else "clean"
        marker = " [main]" if path == ROOT else ""
        print(f"- {branch}{marker}\n    path:  {path}\n    state: {state}")
    return 0


def cmd_remove(branch: str) -> int:
    worktrees = _list_worktrees()
    match = next((w for w in worktrees if w.get("branch") == branch), None)
    if match is None:
        print(f"[git-worktree] FAILED: no worktree checked out on branch '{branch}'. "
              f"Run `list` to see what's available.")
        return 1

    target = Path(match["path"])
    if target == ROOT:
        print("[git-worktree] FAILED: refusing to remove the main worktree.")
        return 1

    status_result = _run(["git", "status", "--porcelain"], cwd=target)
    if status_result.stdout.strip():
        print(f"[git-worktree] FAILED: '{branch}' has uncommitted changes, refusing to remove.\n"
              f"Uncommitted changes in {target}:\n{status_result.stdout}"
              f"\nCommit or stash them yourself first, or if you're sure you want to discard them, "
              f"run `git worktree remove --force {target}` yourself -- this script will not do that for you.")
        return 1

    print(f"[git-worktree] removing worktree at {target} ...")
    remove_result = _run(["git", "worktree", "remove", str(target)])
    if remove_result.returncode != 0:
        print(f"[git-worktree] FAILED to remove worktree:\n{remove_result.stderr}")
        return 1

    branch_del = _run(["git", "branch", "-d", branch])
    if branch_del.returncode != 0:
        print(f"[git-worktree] worktree removed, but local branch '{branch}' was NOT deleted "
              f"(likely has unmerged commits):\n{branch_del.stderr}"
              f"\nDelete it yourself with `git branch -D {branch}` if you're sure, or merge it first.")
        return 0

    print(f"[git-worktree] SUCCESS -- worktree and local branch '{branch}' removed.")
    if _remote_branch_exists(branch):
        print(f"[git-worktree] NOTE: origin/{branch} still exists on GitHub. "
              f"This script will not touch it -- run `review {branch}` first, "
              f"then `delete-remote {branch}` only after the user explicitly agrees.")
    return 0


def cmd_review(branch: str) -> int:
    """Read-only fact-gathering for a branch. Never deletes or modifies anything.

    The local branch is often already gone by the time a remote branch needs
    reviewing (`remove` deletes it once merged) -- so this always compares
    against `origin/<branch>`, not the local ref, which may not exist.
    """
    if not _remote_branch_exists(branch):
        print(f"[git-worktree] '{branch}' has no remote counterpart on origin. Nothing to review remotely.")
        return 0

    ref = f"origin/{branch}"
    _run(["git", "fetch", "origin", branch])

    merge_base = _run(["git", "merge-base", "--is-ancestor", ref, "main"])
    if merge_base.returncode not in (0, 1):
        print(f"[git-worktree] FAILED to compare '{ref}' against main:\n{merge_base.stderr}")
        return 1
    merged = merge_base.returncode == 0

    print(f"[git-worktree] origin/{branch} exists.")
    print(f"[git-worktree] fully merged into main: {merged}")

    if merged:
        log = _run(["git", "log", ref, "--oneline", "-10"])
        print(f"\n[git-worktree] last commits on '{branch}' (for context, already in main):\n{log.stdout or '(empty)'}")
    else:
        commits = _run(["git", "log", f"main...{ref}", "--oneline"])
        diffstat = _run(["git", "diff", f"main...{ref}", "--stat"])
        print(f"\n[git-worktree] commits in '{branch}' not yet in main:\n{commits.stdout or '(none)'}")
        print(f"[git-worktree] diff stat (main...{ref}):\n{diffstat.stdout or '(no diff)'}")

    return 0


def cmd_delete_remote(branch: str) -> int:
    """Pure mechanical remote branch deletion. The calling agent must have
    already gotten explicit user confirmation before invoking this --
    this function does not ask, it just executes."""
    if not _remote_branch_exists(branch):
        print(f"[git-worktree] origin/{branch} does not exist, nothing to delete.")
        return 0

    result = _run(["git", "push", "origin", "--delete", branch])
    if result.returncode != 0:
        print(f"[git-worktree] FAILED to delete origin/{branch}:\n{result.stderr}")
        return 1

    print(f"[git-worktree] SUCCESS -- origin/{branch} deleted.")
    return 0


def cmd_lint_build(subdir: str) -> int:
    """Run `npm run lint` then `npm run build` in <repo>/<subdir>. Pure
    pass/fail check -- does not fix anything, does not decide whether a
    failure blocks a commit (that's the calling agent's call)."""
    target = ROOT / subdir
    if not target.exists():
        print(f"[git-worktree] FAILED: {target} does not exist.")
        return 1

    print(f"[git-worktree] running npm run lint in {target} ...")
    lint_result = _run([NPM_CMD, "run", "lint"], cwd=target)
    print(lint_result.stdout)
    print(lint_result.stderr)
    if lint_result.returncode != 0:
        print("[git-worktree] FAILED: lint did not pass.")
        return 1

    print(f"[git-worktree] running npm run build in {target} ...")
    build_result = _run([NPM_CMD, "run", "build"], cwd=target)
    print(build_result.stdout)
    print(build_result.stderr)
    if build_result.returncode != 0:
        print("[git-worktree] FAILED: build did not pass.")
        return 1

    print("[git-worktree] SUCCESS -- lint and build both passed.")
    return 0


def cmd_pr_comment(pr: str, path: str, line: str, body: str) -> int:
    """Post an inline review comment on a PR at the current head commit.
    Pure mechanical wrapper around `gh api` -- deciding what's worth
    commenting on is the calling agent's job, this just posts it."""
    sha_result = _gh(["api", f"repos/{{owner}}/{{repo}}/pulls/{pr}", "--jq", ".head.sha"])
    if sha_result.returncode != 0:
        print(f"[git-worktree] FAILED to resolve PR #{pr} head sha:\n{sha_result.stderr}")
        return 1
    sha = sha_result.stdout.strip()

    result = _gh([
        "api", f"repos/{{owner}}/{{repo}}/pulls/{pr}/comments",
        "-f", f"commit_id={sha}",
        "-f", f"path={path}",
        "-F", f"line={line}",
        "-f", "side=RIGHT",
        "-f", f"body={body}",
    ])
    if result.returncode != 0:
        print(f"[git-worktree] FAILED to post comment:\n{result.stderr}")
        return 1
    print(f"[git-worktree] SUCCESS -- comment posted on {path}:{line}.")
    return 0


def cmd_pr_reply(comment_id: str, body: str) -> int:
    """Reply within an existing review comment thread (not a new standalone
    comment). Pure mechanical wrapper -- the calling agent decides what the
    reply should say."""
    # The reply endpoint needs the PR number, not just the comment id, so
    # resolve it first rather than guessing at a repo-wide comments list.
    lookup = _gh(["api", f"repos/{{owner}}/{{repo}}/pulls/comments/{comment_id}", "--jq", ".pull_request_url"])
    if lookup.returncode != 0 or not lookup.stdout.strip():
        print(f"[git-worktree] FAILED to resolve PR for comment {comment_id}:\n{lookup.stderr}")
        return 1
    pr_number = lookup.stdout.strip().rsplit("/", 1)[-1]

    result = _gh([
        "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments",
        "-f", f"body={body}",
        "-F", f"in_reply_to={comment_id}",
    ])
    if result.returncode != 0:
        print(f"[git-worktree] FAILED to reply:\n{result.stderr}")
        return 1
    print(f"[git-worktree] SUCCESS -- replied to comment {comment_id}.")
    return 0


def cmd_pr_merge(pr: str, strategy: str) -> int:
    """Merge a PR. Does NOT delete the branch (local or remote) -- that's
    `remove` + `review`/`delete-remote`'s job, run as separate follow-up
    steps. Deliberately not using gh's `--delete-branch`: it tries to
    delete the local branch too, which fails outright if a worktree still
    has it checked out (the common case right after finishing work on it),
    and it deletes the remote branch without going through this skill's
    review-before-delete-remote safety check. The calling agent must
    already have the user's go-ahead to merge before running this -- this
    function does not ask, it just executes."""
    flag = "--squash" if strategy == "squash" else "--merge"
    result = _gh(["pr", "merge", pr, flag])
    if result.returncode != 0:
        print(f"[git-worktree] FAILED to merge PR #{pr}:\n{result.stderr}")
        return 1
    print(f"[git-worktree] SUCCESS -- PR #{pr} merged ({strategy}). "
          f"Branch NOT deleted -- run `remove <branch>` then `review`/`delete-remote <branch>` next.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage git worktrees for this repo.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Create a new worktree + branch.")
    add_parser.add_argument("branch", help="New branch name.")
    add_parser.add_argument("--from", dest="base", default=None, help="Base branch/commit (default: current HEAD).")
    add_parser.add_argument("--push", action="store_true", help="Push the new branch to origin and set upstream.")

    subparsers.add_parser("list", help="List all worktrees and whether each is clean or dirty.")

    remove_parser = subparsers.add_parser("remove", help="Remove a worktree (refuses if it has uncommitted changes).")
    remove_parser.add_argument("branch", help="Branch name whose worktree should be removed.")

    review_parser = subparsers.add_parser(
        "review", help="Read-only: report whether a branch is merged, and its commits/diff vs main."
    )
    review_parser.add_argument("branch", help="Branch name to inspect against main.")

    delete_remote_parser = subparsers.add_parser(
        "delete-remote", help="Delete origin/<branch>. Only run this after the user has explicitly agreed."
    )
    delete_remote_parser.add_argument("branch", help="Branch name to delete on origin.")

    lint_build_parser = subparsers.add_parser(
        "lint-build", help="Run npm run lint then npm run build in a subdirectory (default: frontend)."
    )
    lint_build_parser.add_argument("--dir", dest="subdir", default="frontend", help="Subdirectory to run npm in.")

    pr_comment_parser = subparsers.add_parser(
        "pr-comment", help="Post an inline review comment on a PR at its current head commit."
    )
    pr_comment_parser.add_argument("pr", help="PR number.")
    pr_comment_parser.add_argument("path", help="File path the comment is on.")
    pr_comment_parser.add_argument("line", help="Line number in the file (as it exists in the diff).")
    pr_comment_parser.add_argument("body", help="Comment body.")

    pr_reply_parser = subparsers.add_parser(
        "pr-reply", help="Reply within an existing review comment thread."
    )
    pr_reply_parser.add_argument("comment_id", help="The review comment id to reply to.")
    pr_reply_parser.add_argument("body", help="Reply body.")

    pr_merge_parser = subparsers.add_parser(
        "pr-merge", help="Merge a PR (does not delete the branch -- use remove/delete-remote after). "
                         "Only run after the user has agreed to merge."
    )
    pr_merge_parser.add_argument("pr", help="PR number.")
    pr_merge_parser.add_argument("--strategy", choices=["squash", "merge"], default="squash", help="Merge strategy (default: squash).")

    args = parser.parse_args()

    if args.command == "add":
        return cmd_add(args.branch, args.base, args.push)
    if args.command == "list":
        return cmd_list()
    if args.command == "remove":
        return cmd_remove(args.branch)
    if args.command == "review":
        return cmd_review(args.branch)
    if args.command == "delete-remote":
        return cmd_delete_remote(args.branch)
    if args.command == "lint-build":
        return cmd_lint_build(args.subdir)
    if args.command == "pr-comment":
        return cmd_pr_comment(args.pr, args.path, args.line, args.body)
    if args.command == "pr-reply":
        return cmd_pr_reply(args.comment_id, args.body)
    if args.command == "pr-merge":
        return cmd_pr_merge(args.pr, args.strategy)
    return 1


if __name__ == "__main__":
    sys.exit(main())
