#!/usr/bin/env python3
"""Post (or update) a sticky Kitium report comment on the pull request.

Uses only the stdlib + the GITHUB_TOKEN the Action runner provides. Finds an existing
comment carrying our marker and edits it in place so re-runs don't spam the PR.

Images: the report references images by LOCAL relative path, e.g.
`![Board diff](build/<board>/out/diff/x.png)`. GitHub comments can't show local files,
so before posting we upload each referenced image to a `kitium-bot-assets` branch (via
the Contents API) and rewrite the link to the hosted raw URL. This needs the token to
have `contents: write` — only the fork-safe comment job has it, and it runs no untrusted
code. All image hosting is best-effort: if it fails, the image line degrades to a plain
note and the comment still posts.

Env: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo), KITIUM_PR_NUMBER or GITHUB_EVENT_PATH.

Usage:
    post_comment.py report.md
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

MARKER = "<!-- kitium-report -->"
API = "https://api.github.com"
ASSETS_BRANCH = "kitium-bot-assets"
# Markdown image with a LOCAL (non-http) target: ![alt](path)
_IMG = re.compile(r"!\[([^\]]*)\]\((?!https?://)([^)]+)\)")


def _req(method, url, token, data=None, ok_404=False):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        if ok_404 and e.code == 404:
            return None
        raise


def _pr_number() -> int | None:
    override = os.environ.get("KITIUM_PR_NUMBER", "").strip()
    if override:
        return int(override) if override.isdigit() else None
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        event = json.load(fh)
    return (event.get("pull_request") or {}).get("number")


def _ensure_assets_branch(repo, token):
    """Make sure the assets branch exists; create it from the default branch if not."""
    if _req("GET", f"{API}/repos/{repo}/git/ref/heads/{ASSETS_BRANCH}", token, ok_404=True):
        return True
    info = _req("GET", f"{API}/repos/{repo}", token)
    default = info.get("default_branch", "main")
    ref = _req("GET", f"{API}/repos/{repo}/git/ref/heads/{default}", token)
    sha = ref["object"]["sha"]
    _req("POST", f"{API}/repos/{repo}/git/refs", token,
         {"ref": f"refs/heads/{ASSETS_BRANCH}", "sha": sha})
    return True


def _upload_image(repo, token, dest_path, local_file):
    """PUT the image to the assets branch (create or update); return its raw URL."""
    with open(local_file, "rb") as fh:
        content = base64.b64encode(fh.read()).decode()
    existing = _req("GET", f"{API}/repos/{repo}/contents/{dest_path}?ref={ASSETS_BRANCH}",
                    token, ok_404=True)
    payload = {"message": f"kitium: {dest_path}", "content": content, "branch": ASSETS_BRANCH}
    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]
    resp = _req("PUT", f"{API}/repos/{repo}/contents/{dest_path}", token, payload)
    return (resp.get("content") or {}).get("download_url")


def embed_images(body, base_dir, repo, token, pr, uploader=_upload_image):
    """Rewrite local image links to hosted URLs. Best-effort per image."""
    if not _IMG.search(body):
        return body
    try:
        _ensure_assets_branch(repo, token)
    except Exception as e:  # noqa: BLE001 — hosting is best-effort
        print(f"[kitium] WARN: could not prepare assets branch: {e}", file=sys.stderr)
        return _IMG.sub(lambda m: f"_{m.group(1)} (image in run artifacts)_", body)

    def _sub(m):
        alt, rel = m.group(1), m.group(2).strip()
        local = os.path.join(base_dir, rel)
        if not os.path.isfile(local):
            return f"_{alt} (image not found)_"
        dest = f"pr-{pr}/{re.sub(r'[^A-Za-z0-9._-]', '_', rel)}"
        try:
            url = uploader(repo, token, dest, local)
            return f"![{alt}]({url})" if url else f"_{alt} (image in run artifacts)_"
        except Exception as e:  # noqa: BLE001
            print(f"[kitium] WARN: image upload failed for {rel}: {e}", file=sys.stderr)
            return f"_{alt} (image in run artifacts)_"

    return _IMG.sub(_sub, body)


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
        report = fh.read()
    report = embed_images(report, os.path.dirname(os.path.abspath(argv[0])), repo, token, pr)
    body = f"{MARKER}\n{report}"

    try:
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
        print(f"[kitium] WARN: could not post PR comment: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
