#!/usr/bin/env python3
"""Re-fill copper zones on a converted board, in place.

Why (from research): Altium import brings zones in UNFILLED. If we run DRC, plot
gerbers, or render before filling, copper pours are missing — wrong DRC results and
wrong fabrication output. This refills all zones via the pcbnew API.

Runs INSIDE the KiCad container (needs pcbnew). No-op-safe if there are no zones.

Usage:
    refill_zones.py board.kicad_pcb
"""
import sys


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: refill_zones.py board.kicad_pcb", file=sys.stderr)
        return 1
    path = argv[0]

    try:
        import pcbnew  # provided by KiCad inside the container
    except ImportError:
        print("[kitium] pcbnew not available — run this inside the KiCad container", file=sys.stderr)
        return 1

    board = pcbnew.LoadBoard(path)
    zones = list(board.Zones())
    if not zones:
        print("[kitium] no zones to fill")
        return 0

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(path, board)
    print(f"[kitium] refilled {len(zones)} zone(s) in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
