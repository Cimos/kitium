#!/usr/bin/env python3
"""Inspect a converted .kicad_pcb: emit structural metrics and run pre-flight guards.

Why this exists (from research): Altium PCB import can FAIL SILENTLY — old/ASCII
(Protel) files import to an empty board with no error (gitlab #18467), and some
Altium file versions regress all reference designators to "UNK" (#18502), which
would quietly break the BOM cross-check. So after every import we assert the board
is real before spending time on DRC/gerbers/renders.

Pure stdlib (re/json) so it runs anywhere — no pcbnew needed. The .kicad_pcb is an
s-expression text file; we count by token rather than fully parsing.

Usage:
    pcb_inspect.py board.kicad_pcb [--metrics-out metrics.json] [--assert]

--assert exits non-zero (and prints why) if a guard fails.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Reference designators from modern (property "Reference" "R1") and legacy
# (fp_text reference R1 / "R1") forms.
_REF_PROP = re.compile(r'\(property\s+"Reference"\s+"([^"]*)"')
_REF_FP_TEXT = re.compile(r'\(fp_text\s+reference\s+"?([^"\s\)]+)')


def inspect(text: str) -> dict:
    footprints = len(re.findall(r"\(footprint\s", text)) + len(re.findall(r"\(module\s", text))
    segments = len(re.findall(r"\(segment\b", text)) + len(re.findall(r"\(arc\b", text))
    vias = len(re.findall(r"\(via\b", text))
    zones = len(re.findall(r"\(zone\b", text))
    # Net table entries: (net 0 "") (net 1 "GND") ...
    nets = len(re.findall(r"\(net\s+\d+\s", text))
    # Copper layers declared in the (layers ...) header, e.g. "F.Cu" "In1.Cu" "B.Cu".
    copper_layers = len(re.findall(r'"[A-Za-z0-9]+\.Cu"', text))

    refs = _REF_PROP.findall(text) or _REF_FP_TEXT.findall(text)
    refs = [r for r in refs if r and r not in ("~", "")]
    distinct_refs = sorted(set(refs))
    unk = [r for r in refs if r.upper() == "UNK"]

    return {
        "footprints": footprints,
        "tracks": segments,
        "vias": vias,
        "zones": zones,
        "nets": nets,
        "copper_layers": copper_layers,
        "references_total": len(refs),
        "references_distinct": len(distinct_refs),
        "references_unk": len(unk),
    }


def guards(m: dict) -> list[str]:
    """Return a list of failure messages; empty means the board passed."""
    fails = []
    if m["footprints"] == 0 and m["tracks"] == 0:
        fails.append(
            "board is EMPTY (0 footprints, 0 tracks) — import likely failed silently "
            "(old/ASCII Altium format? see gitlab #18467). Check kicad-cli stderr/report."
        )
    if m["references_total"] > 0 and m["references_unk"] == m["references_total"]:
        fails.append(
            "ALL reference designators are 'UNK' — refdes import regression "
            "(gitlab #18502); BOM cross-check would be meaningless."
        )
    return fails


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Inspect a converted .kicad_pcb.")
    ap.add_argument("board")
    ap.add_argument("--metrics-out")
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args(argv)

    with open(args.board, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    m = inspect(text)
    print(json.dumps(m, indent=2))
    if args.metrics_out:
        with open(args.metrics_out, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=2)

    fails = guards(m)
    for f in fails:
        print(f"[kitium] PRE-FLIGHT FAIL: {f}", file=sys.stderr)

    if args.do_assert and fails:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
