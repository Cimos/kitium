#!/usr/bin/env python3
"""Pick the top-view gerber layers from a directory by filename heuristic, and print
them in stack order (outline, copper, mask, silk) one per line — ready to pass to gerbv.

Works across Altium exports (.GTL/.GTS/.GTO/.GKO) and KiBot/KiCad output, which (when
converted from Altium) keeps Altium-style names like "Top Layer"/"Top Overlay" as well
as canonical "F_Cu"/"F_Silkscreen". Only the top side, so the two renders line up.

Usage: classify_layers.py <gerber_dir>
"""
from __future__ import annotations

import os
import re
import sys

# (role, regex) in stack order: first printed = drawn first (bottom), last = on top.
PATTERNS = [
    ("outline", r"(edge[._ ]?cuts|board[._ ]?outline|keep[._ ]?out|\.gko$|\.gm1$)"),
    ("copper",  r"(top[._ ]?layer|f[._ ]?cu|\.gtl$)"),
    ("mask",    r"(top[._ ]?solder|f[._ ]?mask|\.gts$)"),
    ("silk",    r"(top[._ ]?overlay|top[._ ]?silk|f[._ ]?silk|\.gto$)"),
]


def classify(gerber_dir):
    try:
        files = [os.path.join(gerber_dir, f) for f in sorted(os.listdir(gerber_dir))]
    except OSError:
        return []
    files = [f for f in files if os.path.isfile(f)]
    chosen = []
    for _role, pat in PATTERNS:
        rx = re.compile(pat, re.I)
        match = next((f for f in files if rx.search(os.path.basename(f))), None)
        if match:
            chosen.append(match)
    return chosen


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: classify_layers.py <gerber_dir>", file=sys.stderr)
        return 2
    for f in classify(argv[0]):
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
