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
    drc_gate.py <drc.json> [--severity error] [--summary-out summary.txt]
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Count gateable DRC violations.")
    ap.add_argument("report")
    ap.add_argument("--severity", default="error")
    ap.add_argument("--summary-out")
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

    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
