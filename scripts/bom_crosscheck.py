#!/usr/bin/env python3
"""Cross-check a KiCad (board-derived) BOM against an Altium-exported BOM.

Altium remains the BOM authority. The converted KiCad board only knows
reference designators, values, footprints and quantities — so this checks
*structural parity*: did the conversion drop, add, or mis-count any parts?

It deliberately does NOT compare MPN/manufacturer/supplier fields, because the
PCB import cannot recover them; those stay validated on the Altium side.

Usage:
    bom_crosscheck.py --kicad-bom kicad.csv --altium-bom altium.csv \
        --out bom-diff.md [--fail-on-mismatch]

STATUS: scaffold. Column auto-detection covers common Altium/KiBot exports;
confirm against a real Altium BOM CSV in Phase 4 and extend the candidate lists.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter

# Candidate column headers (matched case-insensitively).
REF_COLS = ["designator", "designators", "references", "reference", "ref", "refdes"]
VALUE_COLS = ["value", "comment", "val"]
QTY_COLS = ["quantity", "qty", "count"]

_SPLIT = re.compile(r"[,;\s]+")


def _find_col(fieldnames, candidates):
    lower = {f.lower().strip(): f for f in (fieldnames or [])}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def load_refs(path):
    """Return a Counter mapping reference designator -> count from a BOM CSV."""
    refs = Counter()
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        # Sniff the delimiter; fall back to comma.
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(fh, dialect=dialect)
        ref_col = _find_col(reader.fieldnames, REF_COLS)
        if not ref_col:
            raise SystemExit(
                f"[kitium] could not find a designator column in {path}; "
                f"saw headers: {reader.fieldnames}"
            )
        for row in reader:
            cell = (row.get(ref_col) or "").strip()
            if not cell:
                continue
            for r in _SPLIT.split(cell):
                r = r.strip()
                if r:
                    refs[r] += 1
    return refs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cross-check KiCad vs Altium BOM by refdes.")
    ap.add_argument("--kicad-bom", required=True)
    ap.add_argument("--altium-bom", required=True)
    ap.add_argument("--out", required=True, help="Markdown report path")
    ap.add_argument("--fail-on-mismatch", action="store_true")
    args = ap.parse_args(argv)

    kicad = load_refs(args.kicad_bom)
    altium = load_refs(args.altium_bom)

    only_altium = sorted(set(altium) - set(kicad))   # dropped during conversion
    only_kicad = sorted(set(kicad) - set(altium))     # appeared unexpectedly
    dupes = sorted(r for r, n in (kicad + altium).items() if (kicad[r] > 1 or altium[r] > 1))

    mismatch = bool(only_altium or only_kicad)

    def _fmt(items, limit=40):
        if not items:
            return "_none_"
        shown = ", ".join(f"`{i}`" for i in items[:limit])
        extra = f" … (+{len(items) - limit} more)" if len(items) > limit else ""
        return shown + extra

    lines = [
        "### BOM cross-check (Altium ↔ KiCad)",
        "",
        f"- Altium designators: **{len(altium)}**",
        f"- KiCad designators: **{len(kicad)}**",
        f"- Missing in KiCad (dropped in conversion): **{len(only_altium)}**",
        f"- Extra in KiCad (not in Altium BOM): **{len(only_kicad)}**",
        "",
        f"**Missing in KiCad:** {_fmt(only_altium)}",
        "",
        f"**Extra in KiCad:** {_fmt(only_kicad)}",
        "",
        f"**Result:** {'⚠️ mismatch' if mismatch else '✅ parity'}",
        "",
    ]
    report = "\n".join(lines)

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(report)

    if mismatch and args.fail_on_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
