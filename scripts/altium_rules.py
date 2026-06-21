#!/usr/bin/env python3
"""Read design rules straight from an Altium .PcbDoc and apply the fidelity-critical
ones to the converted .kicad_pcb, before zone refill.

Why: kicad-cli's Altium importer drops several rules — pour min copper width, per-class
clearances, remove-dead-copper — so KiCad re-pours with its own defaults (e.g. a 0.25mm
min width that over-pulls the copper). The real values ARE in the .PcbDoc.

The .PcbDoc is an OLE compound file (olefile). Its Rules6 / Polygons6 / Classes6 streams
are pipe-delimited KEY=VALUE property records (one record per `|SELECTION=...`). We parse
them and:
  - set every zone's min_thickness to the pour's MINPRIMLENGTH (the direct pour-pullback fix)
  - set the board min clearance + net classes from the Clearance rule's GAP
Everything parsed is also dumped to JSON for transparency (--json-out).

Usage:
  altium_rules.py board.PcbDoc --json-out rules.json          # extract only
  altium_rules.py board.PcbDoc --apply board.kicad_pcb        # extract + apply (needs pcbnew)
"""
from __future__ import annotations

import argparse
import json
import re
import sys

MIL_MM = 0.0254


def _to_mm(value: str):
    """'3mil' -> 0.0762, '0.2mm' -> 0.2, else None."""
    m = re.match(r"\s*([0-9.]+)\s*(mil|mm)?", value or "")
    if not m:
        return None
    n = float(m.group(1))
    return n * MIL_MM if (m.group(2) or "mil") == "mil" else n


def _records(text: str):
    """Split a stream's text into property-record dicts (each starts with |SELECTION=)."""
    out = []
    for chunk in re.split(r"(?=\|SELECTION=)", text):
        if "=" not in chunk:
            continue
        d = dict(re.findall(r"\|([A-Z0-9_]+)=([^|]*)", chunk))
        if d:
            out.append(d)
    return out


def parse_polygons(text: str) -> dict:
    widths = [_to_mm(r["MINPRIMLENGTH"]) for r in _records(text) if r.get("MINPRIMLENGTH")]
    widths = [w for w in widths if w]
    remove_dead = any(r.get("REMOVEDEAD", "").upper() == "TRUE" for r in _records(text))
    return {"pour_min_width_mm": min(widths) if widths else None,
            "remove_dead_copper": remove_dead,
            "polygon_count": sum(1 for r in _records(text) if r.get("POLYGONTYPE"))}


def parse_rules(text: str) -> dict:
    """Group rule records by RULEKIND; pull the values we map to KiCad."""
    by_kind: dict[str, list] = {}
    for r in _records(text):
        kind = r.get("RULEKIND")
        if kind:
            by_kind.setdefault(kind, []).append(r)
    clearance = None
    for r in by_kind.get("Clearance", []):
        g = _to_mm(r.get("GAP", ""))
        if g is not None:
            clearance = g if clearance is None else min(clearance, g)
    width = None
    for r in by_kind.get("Width", []):
        w = _to_mm(r.get("MINLIMIT") or r.get("PREFEREDWIDTH") or "")  # note: one-R, Altium's spelling
        if w is not None:
            width = w if width is None else min(width, w)
    pad_connect = next((r.get("CONNECTSTYLE") for r in by_kind.get("PolygonConnect", [])
                        if r.get("CONNECTSTYLE")), None)
    return {"kinds": sorted(by_kind), "min_clearance_mm": clearance,
            "min_track_width_mm": width, "pad_connect": pad_connect}


def extract(pcbdoc_path: str) -> dict:
    import olefile
    ole = olefile.OleFileIO(pcbdoc_path)

    def read(name):
        try:
            return ole.openstream(name + "/Data").read().decode("latin-1")
        except OSError:
            return ""

    rules = parse_rules(read("Rules6"))
    polys = parse_polygons(read("Polygons6"))
    classes = [m.group(1) for m in re.finditer(r"\|NAME=([^|]+)", read("Classes6"))]
    return {"rules": rules, "polygons": polys, "netclasses": classes}


def apply_to_board(kicad_pcb: str, data: dict) -> None:
    import pcbnew
    b = pcbnew.LoadBoard(kicad_pcb)
    pour = data["polygons"].get("pour_min_width_mm")
    if pour:
        for z in b.Zones():
            z.SetMinThickness(pcbnew.FromMM(pour))
        print(f"[kitium] set zone min_thickness = {pour:.4f}mm (Altium MINPRIMLENGTH)")
    pc = data["rules"].get("pad_connect")
    if pc:
        try:
            mode = {"Direct": pcbnew.ZONE_CONNECTION_FULL,
                    "Relief": pcbnew.ZONE_CONNECTION_THERMAL,
                    "NoConnect": pcbnew.ZONE_CONNECTION_NONE}.get(pc)
            if mode is not None:
                for z in b.Zones():
                    z.SetPadConnection(mode)
                print(f"[kitium] set zone pad connection = {pc} (Altium PolygonConnect)")
        except Exception:  # noqa: BLE001 — pad-connection API varies by KiCad version
            pass
    rd = data["polygons"].get("remove_dead_copper")
    if rd is not None:
        try:
            mode = (pcbnew.ISLAND_REMOVAL_MODE_ALWAYS if rd
                    else pcbnew.ISLAND_REMOVAL_MODE_NEVER)
            for z in b.Zones():
                z.SetIslandRemovalMode(mode)
            print(f"[kitium] set island removal = {'ALWAYS' if rd else 'NEVER'} (Altium REMOVEDEAD)")
        except Exception:  # noqa: BLE001 — island-removal API varies by KiCad version
            pass
    clr = data["rules"].get("min_clearance_mm")
    if clr:
        b.GetDesignSettings().m_MinClearance = pcbnew.FromMM(clr)
        try:
            for nc in b.GetAllNetClasses().values():
                nc.SetClearance(pcbnew.FromMM(clr))
        except Exception:  # noqa: BLE001 — netclass API varies by KiCad version
            pass
        print(f"[kitium] set min clearance = {clr:.4f}mm (Altium Clearance GAP)")
    pcbnew.SaveBoard(kicad_pcb, b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read Altium .PcbDoc design rules.")
    ap.add_argument("pcbdoc")
    ap.add_argument("--apply", metavar="BOARD.kicad_pcb")
    ap.add_argument("--json-out")
    args = ap.parse_args(argv)

    try:
        data = extract(args.pcbdoc)
    except Exception as e:  # noqa: BLE001 — never break the gate over rule extraction
        print(f"[kitium] WARN: could not read Altium rules ({e}) — using KiCad defaults", file=sys.stderr)
        return 0

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    print(json.dumps(data, indent=2))

    if args.apply:
        try:
            apply_to_board(args.apply, data)
        except Exception as e:  # noqa: BLE001
            print(f"[kitium] WARN: could not apply rules ({e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
