#!/usr/bin/env python3
"""Post (or update) a sticky Kitium report comment on the pull request.

Phase 3 reporting. Uses only the stdlib + the GITHUB_TOKEN the Action runner
provides. Finds an existing comment carrying our marker and edits it in place so
re-runs don't spam the PR; otherwise creates one.

Env: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), GITHUB_EVENT_PATH (to read the
PR number). No-ops gracefully when not running on a pull_request event.

Usage:
    post_comment.py report.md
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

MARKER = "<!-- kitium-report -->"
API = "https://api.github.com"


def _req(method, url, token, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or "null")


def _pr_number() -> int | None:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        event = json.load(fh)
    pr = event.get("pull_request") or {}
    return pr.get("number")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: post_comment.py report.md", file=sys.stderr)
        return 1

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("INPUT_GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr = _pr_number()
    if not (token and repo and pr):
        print("[kitium] not a PR event (or no token) — skipping comment post")
        return 0

    with open(argv[0], encoding="utf-8") as fh:
        body = f"{MARKER}\n{fh.read()}"

    try:
        # Page through ALL comments — the sticky comment can scroll past the first
        # 100 on a busy PR, which would otherwise make us post a duplicate each run.
        existing = None
        page = 1
        while existing is None:
            batch = _req("GET", f"{API}/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}", token) or []
            existing = next((c for c in batch if MARKER in (c.get("body") or "")), None)
            if len(batch) < 100:
                break
            page += 1
        if existing:
            _req("PATCH", f"{API}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": body})
            print(f"[kitium] updated PR comment {existing['id']}")
        else:
            _req("POST", f"{API}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
            print("[kitium] created PR comment")
    except urllib.error.HTTPError as e:
        # Never fail the whole gate just because commenting didn't work.
        print(f"[kitium] WARN: could not post PR comment: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
