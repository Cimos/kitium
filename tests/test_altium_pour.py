#!/usr/bin/env python3
"""Tests for scripts/altium_pour.py binary parsers (pure — no olefile/pcbnew)."""
import importlib.util
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "altium_pour", os.path.join(HERE, "..", "scripts", "altium_pour.py"))
ap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ap)


def _shape_geo(verts):
    """Build a ShapeBasedRegions6 vertex blob: int32 N, then (straight) 37-byte verts."""
    out = struct.pack("<I", len(verts))
    for x_mil, y_mil in verts:
        out += bytes([0])                                   # straight-segment flag
        out += struct.pack("<i", int(x_mil * 10000))        # x in 1/10000 mil
        out += struct.pack("<i", int(y_mil * 10000))        # y
        out += b"\x00" * 28                                 # arc payload (zero)
    return out


def _record(body):
    return b"\x0b" + struct.pack("<I", len(body)) + body


def _body(net, poly, prop, geo):
    head = bytearray(22)
    struct.pack_into("<h", head, 3, net)
    struct.pack_into("<h", head, 5, poly)
    struct.pack_into("<I", head, 18, len(prop))
    return bytes(head) + prop.encode("latin-1") + geo


def test_mil():
    assert abs(ap._mil("3105mil") - 78.867) < 1e-3
    assert ap._mil("") == 0.0


def test_verts_shape_decodes_and_no_arc():
    geo = _shape_geo([(1000.0, 1005.0), (3105.0, 1005.0), (3105.0, 1885.0)])
    pts, had_arc = ap._verts_shape(geo)
    assert had_arc is False
    assert len(pts) == 3
    assert abs(pts[0][0] - 1000.0 * 0.0254) < 1e-6   # mm
    assert abs(pts[1][0] - 3105.0 * 0.0254) < 1e-6


def test_verts_shape_flags_arc():
    geo = bytearray(_shape_geo([(1.0, 1.0), (2.0, 2.0)]))
    geo[4] = 0x01            # set the segment flag on the first vertex
    _, had_arc = ap._verts_shape(bytes(geo))
    assert had_arc is True


def test_verts_region_doubles():
    geo = struct.pack("<I", 2) + struct.pack("<dd", 27500000.0, 10050000.0) \
        + struct.pack("<dd", 31000000.0, 10050000.0)
    pts, had_arc = ap._verts_region(geo)
    assert had_arc is False
    assert abs(pts[0][0] - 2750.0 * 0.0254) < 1e-6   # 27500000/10000 mil -> mm


def test_records_framing_and_region_grouping():
    geo = _shape_geo([(0, 0), (10, 0), (10, 10), (0, 10)])
    prop = "|V7_LAYER=TOP|NAME= |KIND=0|SUBPOLYINDEX=0|"
    data = _record(_body(net=-1, poly=1, prop=prop, geo=geo)) * 2  # two regions, same poly
    # feed through the grouping logic the way parse_regions does
    groups = {}
    for body in ap._records(data):
        poly_idx = struct.unpack_from("<h", body, 5)[0]
        proplen = struct.unpack_from("<I", body, 18)[0]
        p = body[22:22 + proplen].decode("latin-1")
        import re
        d = dict(re.findall(r"([A-Z0-9_]+)=([^|]*)", p))
        pts, _ = ap._verts_shape(body[22 + proplen:])
        g = groups.setdefault(poly_idx, {"layer": d.get("V7_LAYER"), "polys": []})
        g["polys"].append(pts)
    assert list(groups) == [1]
    assert groups[1]["layer"] == "TOP"
    assert len(groups[1]["polys"]) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: altium_pour tests passed")
