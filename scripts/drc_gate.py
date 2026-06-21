#!/usr/bin/env python3
"""Count gateable DRC violations in a KiBot/KiCad DRC JSON report.

KiBot's `drc` preflight (format JSON) emits KiCad's native DRC JSON:
  {"violations": [{"type","severity","description","items","excluded"}, ...],
   "unconnected_items": [...], "schematic_parity": [...], ...}

KiBot applies `drc.filters` (change_to: ignore) by annotating each filtered violation
with `excluded: true` IN PLACE — it does NOT remove them from this raw KiCad JSON. So
the gateable count = error-severity violations that are NOT excluded. That's the signal
entrypoint.sh uses to decide `block` mode. Renders/BOM never reach this path.

Usage:
    drc_gate.py <drc.json> [--severity error] [--summary-out summary.txt] [--md-out drc.md]
Prints the count (and a per-type breakdown); exits 1 if count > 0, else 0.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys


def gateable(report: dict, severity: str) -> list:
    return [
        v for v in report.get("violations", [])
        if v.get("severity") == severity and not v.get("excluded")
    ]


def filtered(report: dict) -> list:
    # Import artifacts KiBot suppressed via drc.filters (still in the JSON, marked).
    return [v for v in report.get("violations", []) if v.get("excluded")]


def _md_table(counter) -> str:
    rows = "\n".join(f"| {n} | `{t}` |" for t, n in counter.most_common())
    return "| Count | Violation type |\n| ---: | --- |\n" + rows


def _markdown(viol: list, filt: list, severity: str) -> str:
    by_type = collections.Counter(v.get("type", "?") for v in viol)
    lines = [f"**DRC: {len(viol)} post-filter {severity}(s)** "
             f"— {len(filt)} import artifacts auto-filtered."]
    if by_type:
        lines += ["", _md_table(by_type)]
    if filt:
        filt_by_type = collections.Counter(v.get("type", "?") for v in filt)
        lines += ["", "<details><summary>Filtered import artifacts (not real defects)</summary>",
                  "", _md_table(filt_by_type), "</details>"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Count gateable DRC violations.")
    ap.add_argument("report")
    ap.add_argument("--severity", default="error")
    ap.add_argument("--summary-out")
    ap.add_argument("--md-out", help="Write a Markdown DRC table for the PR comment")
    args = ap.parse_args(argv)

    # Fail closed on an unreadable/truncated report, but with a legible reason
    # instead of a bare traceback (entrypoint treats our non-zero exit as a gate fail).
    try:
        with open(args.report, encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"DRC report unreadable ({args.report}): {e}", file=sys.stderr)
        return 1

    viol = gateable(report, args.severity)
    by_type = collections.Counter(v.get("type", "?") for v in viol)
    breakdown = "\n".join(f"{n}\t{t}" for t, n in by_type.most_common())

    print(f"gateable {args.severity} violations: {len(viol)}")
    if breakdown:
        print(breakdown)

    if args.summary_out:
        with open(args.summary_out, "w", encoding="utf-8") as fh:
            fh.write(f"Post-filter DRC {args.severity} violations: {len(viol)}\n")
            if breakdown:
                fh.write(breakdown + "\n")

    if args.md_out:
        with open(args.md_out, "w", encoding="utf-8") as fh:
            fh.write(_markdown(viol, filtered(report), args.severity))

    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
