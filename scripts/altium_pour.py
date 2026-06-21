#!/usr/bin/env python3
"""Import Altium's ACTUAL poured copper into the converted KiCad board, instead of
re-pouring zones with KiCad's fill engine.

Why: kicad-cli imports Altium zones UNFILLED, so we normally re-pour them in KiCad.
But KiCad's fill engine makes different connectivity/island decisions than Altium
(see docs), so the re-poured copper never byte-matches Altium. Altium, however, stores
its real poured copper in the .PcbDoc — the same geometry the published gerbers are
plotted from. This reads that geometry and injects it as each zone's locked fill, so
the copper is exactly Altium's. Altium stays the source of truth; we never re-pour.

Format (reverse-engineered, cross-checked against altium2kicad's format facts):
  ShapeBasedRegions6/Data is a sequence of records:
    uint8 tag (0x0B) | int32 block_len | body[block_len]
  body: net=int16@3, polygon=int16@5, proplen=int32@18, prop@22 (pipe ASCII:
        |V7_LAYER=TOP|NAME=|KIND=0|SUBPOLYINDEX=..), then int32 N, then (N+1) verts.
  vertex (37 bytes): uint8 seg-flag@+0 (0=straight, !=0=arc), int32 x@+1, int32 y@+5,
        28-byte arc payload@+9 (zero for straight). Coords are 1/10000 mil.
  Regions6/Data is the older form: 16-byte double verts (no arc flag), N verts.

Known limits (logged, never fatal — falls back to re-pour): arc segments are linearised
(straight) because no test board exercised the 28-byte arc payload; explicit hole
contours (KIND!=0 / separate SUBPOLYINDEX voids) are not subtracted — boards whose pour
encodes voids inline in the main contour (the common case) import faithfully.

Usage:
  altium_pour.py board.PcbDoc --apply board.kicad_pcb     # inject Altium pour (needs pcbnew)
  altium_pour.py board.PcbDoc --dump                       # parse + report only
"""
from __future__ import annotations

import argparse
import math
import re
import struct
import sys

RAW_TO_MM = 0.0254 / 10000.0   # 1/10000 mil -> mm
MIL_TO_MM = 0.0254


def _open(pcbdoc):
    import olefile
    return olefile.OleFileIO(pcbdoc)


def _read(ole, name):
    try:
        return ole.openstream(name + "/Data").read()
    except OSError:
        return b""


def parse_nets(ole) -> list:
    """Net names in Nets6 record order (region net index is 0-based into this)."""
    return [m.decode("latin-1") for m in re.findall(rb"\|NAME=([^|]*)", _read(ole, "Nets6"))]


def parse_polygons(ole) -> list:
    """Altium polygons (Polygons6 is pipe-ASCII), IN STREAM ORDER (region poly index
    points here). Each: layer name, net index (into Nets6), outline bbox in mm."""
    out = []
    text = _read(ole, "Polygons6").decode("latin-1")
    for chunk in re.split(r"(?=\|SELECTION=)", text):
        if "POLYGONTYPE=" not in chunk:
            continue
        d = dict(re.findall(r"\|([A-Z0-9_]+)=([^|]*)", chunk))
        xs, ys = [], []
        i = 0
        while f"VX{i}" in d:
            xs.append(_mil(d[f"VX{i}"]))
            ys.append(_mil(d[f"VY{i}"]))
            i += 1
        nm = re.match(r"\s*(-?\d+)", d.get("NET", ""))
        out.append({"layer": d.get("LAYER", ""),
                    "net_idx": int(nm.group(1)) if nm else -1,
                    "bbox": (min(xs), max(xs), min(ys), max(ys)) if xs else None})
    return out


def _mil(s):
    m = re.match(r"\s*(-?[0-9.]+)", s or "")
    return float(m.group(1)) * MIL_TO_MM if m else 0.0


def _records(data):
    """Yield (body bytes) for each 0x0B-tagged length-prefixed record."""
    off = 0
    while off + 5 <= len(data) and data[off] == 0x0B:
        blen = struct.unpack_from("<I", data, off + 1)[0]
        if blen == 0 or off + 5 + blen > len(data):
            break
        yield data[off + 5:off + 5 + blen]
        off += 5 + blen


def _read_doubles_contour(geo, off):
    """[uint32 n][n × (double x, double y)] in 1/10000 mil. Returns (pts, next_off).

    Advances next_off past the full claimed count even on bad data, so later contours stay
    aligned. Returns [] (drop the contour) if any vertex is non-finite or absurdly large —
    a corruption guard so a malformed hole can never inject garbage copper geometry."""
    n = struct.unpack_from("<I", geo, off)[0]
    off += 4
    pts, bad = [], False
    for _ in range(n):
        if off + 16 > len(geo):
            bad = True
            break
        x, y = struct.unpack_from("<dd", geo, off)
        off += 16
        xm, ym = x * RAW_TO_MM, y * RAW_TO_MM
        if not (math.isfinite(xm) and math.isfinite(ym)) or abs(xm) > 1e5 or abs(ym) > 1e5:
            bad = True
            continue
        pts.append((xm, ym))
    return ([] if bad else pts), off


def _shape_record(geo, hole_count):
    """ShapeBasedRegions6 region: a 37-byte-vertex outer ring (N+1, closed) followed by
    `hole_count` void contours stored as 16-byte double vertices. Returns (outer, holes,
    had_arc). Voids MUST be subtracted or the pour fills solid over the traces."""
    n = struct.unpack_from("<I", geo, 0)[0]
    outer, had_arc = [], False
    for i in range(n):
        base = 4 + i * 37
        if base + 9 > len(geo):
            break
        if geo[base] != 0:
            had_arc = True
        x = struct.unpack_from("<i", geo, base + 1)[0] * RAW_TO_MM
        y = struct.unpack_from("<i", geo, base + 5)[0] * RAW_TO_MM
        outer.append((x, y))
    holes = []
    off = 4 + (n + 1) * 37   # skip the closing duplicate vertex
    for _ in range(max(0, hole_count)):
        if off + 4 > len(geo):
            break
        hpts, off = _read_doubles_contour(geo, off)
        if len(hpts) >= 3:
            holes.append(hpts)
    return outer, holes, had_arc


def _region_record(geo, hole_count):
    """Regions6 (older): 16-byte double outer ring, then `hole_count` double contours."""
    outer, off = _read_doubles_contour(geo, 0)
    holes = []
    for _ in range(max(0, hole_count)):
        if off + 4 > len(geo):
            break
        hpts, off = _read_doubles_contour(geo, off)
        if len(hpts) >= 3:
            holes.append(hpts)
    return outer, holes, False


def _is_copper_layer(name) -> bool:
    """True for Altium copper layers (TOP/BOTTOM/MIDn/PLANEn); False for paste/silk/mask."""
    n = (name or "").upper()
    return n in ("TOP", "BOTTOM") or bool(re.fullmatch(r"(?:MID|PLANE|INTERNALPLANE)\d+", n))


def parse_regions(ole) -> dict:
    """Poured-copper regions grouped by parent polygon index. Prefers ShapeBasedRegions6.

    Regions carry net=-1; the net comes via the parent polygon (poly index at body+5). Each
    region is an outer ring plus zero or more void contours (count at body offset 14) which
    must be subtracted. Returns {"groups": {poly_idx: {"layer", "shapes": [(outer, holes)]}},
    "had_arc", "source"}.
    """
    for stream, decode in (("ShapeBasedRegions6", _shape_record), ("Regions6", _region_record)):
        data = _read(ole, stream)
        if not data:
            continue
        groups, had_arc = {}, False
        for body in _records(data):
            if len(body) < 22:
                continue
            poly_idx = struct.unpack_from("<h", body, 5)[0]
            hole_count = struct.unpack_from("<h", body, 14)[0]
            proplen = struct.unpack_from("<I", body, 18)[0]
            prop = body[22:22 + proplen].decode("latin-1", "replace")
            d = dict(re.findall(r"([A-Z0-9_]+)=([^|]*)", prop))
            if d.get("KIND") not in (None, "0"):   # 0 = copper; skip cavities/cutouts
                continue
            layer = d.get("V7_LAYER", "")
            if not _is_copper_layer(layer):         # skip paste/overlay/soldermask regions
                continue
            geo = body[22 + proplen:]
            if len(geo) < 4:
                continue
            outer, holes, arc = decode(geo, hole_count)
            had_arc = had_arc or arc
            if len(outer) >= 3:
                g = groups.setdefault(poly_idx, {"layer": layer, "shapes": []})
                g["shapes"].append((outer, holes))
        if groups:
            return {"groups": groups, "had_arc": had_arc, "source": stream}
    return {"groups": {}, "had_arc": False, "source": None}


# --- KiCad layer mapping (Altium name -> KiCad layer ID) ---------------------
# Match by layer ID, NOT display name: Altium-imported boards keep names like
# "Top Layer", so string compares against "F.Cu" would fail.
def _layer_id(pcbnew, alt_name):
    n = (alt_name or "").upper()
    if n == "TOP":
        return pcbnew.F_Cu
    if n == "BOTTOM":
        return pcbnew.B_Cu
    m = re.match(r"(?:MID|PLANE)(\d+)", n)
    if m:
        return getattr(pcbnew, f"In{m.group(1)}_Cu", None)
    return None


def apply_to_board(kicad_pcb, data) -> bool:
    """Inject Altium's poured copper as each matching zone's locked fill. Returns True on
    success (caller then SKIPS the KiCad re-pour); False to fall back to re-pour."""
    import pcbnew
    groups = data["groups"]
    if not groups:
        print("[kitium] altium_pour: no poured regions found — falling back to re-pour", file=sys.stderr)
        return False
    if data["had_arc"]:
        print("[kitium] altium_pour: WARN arc segments present — linearised (straight); "
              "rounded pour corners may differ slightly", file=sys.stderr)

    b = pcbnew.LoadBoard(kicad_pcb)
    nets, polygons = data["nets"], data["polygons"]

    # Per-board transform: Altium absolute coords -> KiCad nm. Pure translation + Y-flip,
    # scale 1. Derived from the largest zone outline bbox matched to its Altium polygon.
    tf = _derive_transform(b, polygons)
    if tf is None:
        print("[kitium] altium_pour: could not derive coordinate transform — falling back", file=sys.stderr)
        return False
    ox_mm, c_mm = tf

    def to_nm(xy):
        return pcbnew.VECTOR2I(pcbnew.FromMM(xy[0] + ox_mm), pcbnew.FromMM(c_mm - xy[1]))

    applied = 0
    for poly_idx, g in groups.items():
        layer_id = _layer_id(pcbnew, g["layer"])
        if layer_id is None:
            continue
        net_name = ""
        if 0 <= poly_idx < len(polygons):
            ni = polygons[poly_idx]["net_idx"]
            net_name = nets[ni] if 0 <= ni < len(nets) else ""
        zone = _zone_on_layer_net(b, layer_id, net_name)
        if zone is None:
            continue
        def _chain(poly):
            c = pcbnew.SHAPE_LINE_CHAIN()
            for xy in poly:
                p = to_nm(xy)
                c.Append(p.x, p.y)
            c.SetClosed(True)
            return c

        sps = pcbnew.SHAPE_POLY_SET()
        nholes = 0
        for outer, holes in g["shapes"]:
            idx = sps.AddOutline(_chain(outer))
            for hole in holes:                      # subtract voids — else the pour fills solid
                sps.AddHole(_chain(hole), idx)
                nholes += 1
        # KiCad's saved filled_polygons must be hole-free: fracture stitches each void into
        # its outline with a cut slit. Without this the holes are dropped on save (solid pour).
        sps.Fracture()
        zone.SetFilledPolysList(zone.GetLayer(), sps)
        zone.SetIsFilled(True)
        applied += 1
        print(f"[kitium] altium_pour: {g['layer']}/{net_name or '<no-net>'} -> "
              f"{len(g['shapes'])} region(s), {nholes} void(s) injected as locked fill")

    if applied == 0:
        print("[kitium] altium_pour: no zones matched the poured regions — falling back", file=sys.stderr)
        return False
    pcbnew.SaveBoard(kicad_pcb, b)
    print(f"[kitium] altium_pour: imported Altium's pour into {applied} zone(s) "
          f"(source: {data['source']}); skipping re-pour")
    return True


def _zone_on_layer_net(b, layer_id, net_name):
    for z in b.Zones():
        if z.GetLayer() == layer_id and z.GetNetname() == net_name:
            return z
    return None


def _derive_transform(b, polygons):
    """Solve (offset_x_mm, yflip_const_mm) from the biggest zone outline vs its Altium
    polygon bbox. x_kicad = x_alt + ox ; y_kicad = c - y_alt."""
    import pcbnew
    best = None
    for z in b.Zones():
        ol = z.Outline()
        if ol.OutlineCount() == 0:
            continue
        chain = ol.Outline(0)
        if chain.PointCount() < 3:
            continue
        xs = [pcbnew.ToMM(chain.CPoint(i).x) for i in range(chain.PointCount())]
        ys = [pcbnew.ToMM(chain.CPoint(i).y) for i in range(chain.PointCount())]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if best is None or area > best[0]:
            best = (area, min(xs), max(xs), min(ys), max(ys), z.GetLayer())
    if best is None:
        return None
    _, kx0, kx1, ky0, ky1, klayer_id = best
    # find the Altium polygon on the same KiCad layer with the closest-size bbox
    cand = None
    for p in polygons:
        if p["bbox"] is None or _layer_id(pcbnew, p["layer"]) != klayer_id:
            continue
        ax0, ax1, ay0, ay1 = p["bbox"]
        sizediff = abs((ax1 - ax0) - (kx1 - kx0)) + abs((ay1 - ay0) - (ky1 - ky0))
        if cand is None or sizediff < cand[0]:
            cand = (sizediff, ax0, ax1, ay0, ay1)
    if cand is None:
        return None
    _, ax0, ax1, ay0, ay1 = cand
    ox = kx0 - ax0
    c = ky0 + ay1   # KiCad min-y corresponds to Altium max-y (Y flip)
    if abs((kx1 - ax1) - ox) > 0.1 or abs((ky1 + ay0) - c) > 0.1:   # other corner must agree
        return None
    return ox, c


def extract(pcbdoc) -> dict:
    ole = _open(pcbdoc)
    data = parse_regions(ole)
    data["nets"] = parse_nets(ole)
    data["polygons"] = parse_polygons(ole)
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import Altium's stored poured copper into KiCad.")
    ap.add_argument("pcbdoc")
    ap.add_argument("--apply", metavar="BOARD.kicad_pcb")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args(argv)

    try:
        data = extract(args.pcbdoc)
    except Exception as e:  # noqa: BLE001 — never break the gate over pour import
        print(f"[kitium] altium_pour: WARN could not read pour ({e}) — falling back to re-pour",
              file=sys.stderr)
        return 0

    if args.dump:
        print(f"source={data['source']} nets={len(data['nets'])} "
              f"polygons={len(data['polygons'])} had_arc={data['had_arc']}")
        for poly_idx, g in data["groups"].items():
            net = "?"
            if 0 <= poly_idx < len(data["polygons"]):
                ni = data["polygons"][poly_idx]["net_idx"]
                net = data["nets"][ni] if 0 <= ni < len(data["nets"]) else "?"
            nholes = sum(len(h) for _, h in g["shapes"])
            print(f"  poly{poly_idx} {g['layer']}/{net}: {len(g['shapes'])} region(s), "
                  f"{nholes} void(s), outer_verts={[len(o) for o, _ in g['shapes']]}")

    if args.apply:
        try:
            ok = apply_to_board(args.apply, data)
        except Exception as e:  # noqa: BLE001
            print(f"[kitium] altium_pour: WARN apply failed ({e}) — falling back to re-pour",
                  file=sys.stderr)
            return 0
        # exit code signals the entrypoint whether to skip refill (0=applied, 3=fall back)
        return 0 if ok else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
