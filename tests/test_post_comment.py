#!/usr/bin/env python3
"""Plain-assert unit tests for scripts/post_comment.py (no pytest dependency).

Covers the logic that runs WITHOUT hitting the GitHub API: PR-number parsing from
the event payload, and the fail-soft no-op when this isn't a PR / there's no token.
The actual comment upsert is exercised on a real PR in Phase 3 validation.
"""
import importlib.util
import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_PATH = os.path.join(HERE, "..", "scripts", "post_comment.py")

_spec = importlib.util.spec_from_file_location("post_comment", MOD_PATH)
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def _clear_env():
    for k in ("GITHUB_TOKEN", "INPUT_GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH"):
        os.environ.pop(k, None)


def test_pr_number_none_without_event():
    _clear_env()
    assert pc._pr_number() is None


def test_pr_number_reads_event_payload():
    _clear_env()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"pull_request": {"number": 42}}, fh)
        os.environ["GITHUB_EVENT_PATH"] = fh.name
    try:
        assert pc._pr_number() == 42
    finally:
        os.unlink(os.environ.pop("GITHUB_EVENT_PATH"))


def test_main_noop_without_token(capsys_path=None):
    # No token/repo/PR -> must return 0 (never fail the gate) and not raise.
    _clear_env()
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write("# report")
        report = fh.name
    try:
        assert pc.main([report]) == 0
    finally:
        os.unlink(report)


def test_main_usage_error_without_args():
    _clear_env()
    assert pc.main([]) == 1


def test_embed_images_rewrites_local_to_hosted():
    pc._ensure_assets_branch = lambda repo, token: True  # don't hit the API
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "diff.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n")
        out = pc.embed_images("look ![Board diff](diff.png) done", d, "o/r", "tok", 7,
                              uploader=lambda repo, token, dest, local: "https://h/x.png")
    assert "![Board diff](https://h/x.png)" in out, out


def test_embed_images_missing_file_degrades_gracefully():
    pc._ensure_assets_branch = lambda repo, token: True
    out = pc.embed_images("![X](nope.png)", "/tmp", "o/r", "tok", 7,
                          uploader=lambda *a: "unused")
    assert "image not found" in out and "![X]" not in out, out


def test_embed_images_noop_without_images():
    body = "no images here"
    assert pc.embed_images(body, "/tmp", "o/r", "tok", 7) == body


if __name__ == "__main__":
    test_pr_number_none_without_event()
    test_pr_number_reads_event_payload()
    test_main_noop_without_token()
    test_main_usage_error_without_args()
    test_embed_images_rewrites_local_to_hosted()
    test_embed_images_missing_file_degrades_gracefully()
    test_embed_images_noop_without_images()
    print("OK: post_comment tests passed")
