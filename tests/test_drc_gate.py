#!/usr/bin/env python3
"""Plain-assert unit tests for scripts/drc_gate.py (no pytest dependency)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "scripts", "drc_gate.py")


def _run(report: dict, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(report, fh)
        path = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, GATE, path, *args],
            capture_output=True, text=True,
        )
        return proc
    finally:
        os.unlink(path)


def test_counts_only_unexcluded_error_severity():
    # KiBot annotates filtered violations with excluded=true IN PLACE (it does not
    # remove them from the raw KiCad JSON). The gate must ignore those.
    report = {"violations": [
        {"type": "tracks_crossing", "severity": "error"},
        {"type": "clearance", "severity": "error", "excluded": True},  # filtered -> ignore
        {"type": "silk_overlap", "severity": "warning"},
    ]}
    proc = _run(report)
    assert proc.returncode == 1, proc.stderr
    assert "gateable error violations: 1" in proc.stdout, proc.stdout


def test_clean_report_exits_zero():
    report = {"violations": [{"type": "silk_overlap", "severity": "warning"}]}
    proc = _run(report)
    assert proc.returncode == 0, proc.stderr
    assert "gateable error violations: 0" in proc.stdout, proc.stdout


def test_missing_violations_key_is_clean():
    proc = _run({"unconnected_items": []})
    assert proc.returncode == 0, proc.stderr


def test_malformed_json_fails_closed():
    # A truncated/non-JSON report must fail closed (exit 1) with a legible message,
    # not a bare traceback — entrypoint treats our non-zero exit as a gate failure.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write("{ this is not valid json")
        path = fh.name
    try:
        proc = subprocess.run([sys.executable, GATE, path], capture_output=True, text=True)
        assert proc.returncode == 1, proc.stdout
        assert "unreadable" in proc.stderr.lower(), proc.stderr
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_counts_only_unexcluded_error_severity()
    test_clean_report_exits_zero()
    test_missing_violations_key_is_clean()
    test_malformed_json_fails_closed()
    print("OK: drc_gate tests passed")
