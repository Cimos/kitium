#!/usr/bin/env python3
"""Derive a flat BOM (Reference, Value, Footprint) from a .kicad_pcb.

Why this exists (from research + review): KiCad has NO board-only BOM — neither
`kicad-cli pcb export bom` (doesn't exist, gitlab #16302) nor KiBot's `bom` output
(schematic-derived: out_bom.py loads components from the schematic, not the board).
A board-only import has no schematic, so we extract the component list straight from
the imported board ourselves, then bom_crosscheck.py compares it to the Altium CSV.

Pure stdlib. The .kicad_pcb is s-expression text; we slice each (footprint ...)
block by paren-matching (a heuristic — robust enough for refdes/value/fpid).

Usage:
    pcb_bom.py board.kicad_pcb --out bom.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys

_FP_ID = re.compile(r'\(footprint\s+"?([^"\s\)]+)')
_REF = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')
_VAL = re.compile(r'\(property\s+"Value"\s+"([^"]*)"')
_REF_LEGACY = re.compile(r'\(fp_text\s+reference\s+"?([^"\s\)]+)')
_VAL_LEGACY = re.compile(r'\(fp_text\s+value\s+"?([^"\s\)]+)')


def footprint_blocks(text: str):
    """Yield each top-level (footprint ...) block via paren matching."""
    token = "(footprint"
    i = 0
    while True:
        idx = text.find(token, i)
        if idx < 0:
            return
        depth = 0
        j = idx
        end = -1
        while j < len(text):
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if end < 0:
            return
        yield text[idx:end + 1]
        i = end + 1


def _first(*matches):
    for m in matches:
        if m:
            return m.group(1)
    return ""


def extract(text: str):
    rows = []
    for block in footprint_blocks(text):
        ref = _first(_REF.search(block), _REF_LEGACY.search(block))
        if not ref or ref in ("~", ""):
            continue
        val = _first(_VAL.search(block), _VAL_LEGACY.search(block))
        fpid = (_FP_ID.search(block).group(1) if _FP_ID.search(block) else "")
        rows.append((ref, val, fpid))
    rows.sort()
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Derive a flat BOM from a .kicad_pcb.")
    ap.add_argument("board")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    with open(args.board, encoding="utf-8", errors="replace") as fh:
        rows = extract(fh.read())

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reference", "Value", "Footprint"])
        w.writerows(rows)

    print(f"[kitium] derived BOM: {len(rows)} components -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
