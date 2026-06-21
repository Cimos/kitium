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
    """Build a ShapeBasedRegions6 outer ring: header N=len(verts), then N+1 37-byte verts
    (the last duplicates the first, matching Altium's closed-ring convention)."""
    out = struct.pack("<I", len(verts))
    for x_mil, y_mil in list(verts) + [verts[0]]:
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


def _hole_doubles(pts):
    out = struct.pack("<I", len(pts))
    for x_mil, y_mil in pts:
        out += struct.pack("<dd", x_mil * 10000, y_mil * 10000)   # 1/10000 mil doubles
    return out


def test_shape_record_outer_no_arc():
    # _shape_geo appends the closing dup; _shape_record reads N and drops it
    geo = _shape_geo([(1000.0, 1005.0), (3105.0, 1005.0), (3105.0, 1885.0), (1000.0, 1885.0)])
    outer, holes, had_arc = ap._shape_record(geo, 0)
    assert had_arc is False and holes == []
    assert len(outer) == 4
    assert abs(outer[0][0] - 1000.0 * 0.0254) < 1e-6   # mm


def test_shape_record_flags_arc():
    geo = bytearray(_shape_geo([(1.0, 1.0), (2.0, 2.0)]))
    geo[4] = 0x01            # segment flag on the first vertex
    _, _, had_arc = ap._shape_record(bytes(geo), 0)
    assert had_arc is True


def test_shape_record_subtracts_hole():
    geo = _shape_geo([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)])      # triangle ring (N=3)
    geo += _hole_doubles([(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)])  # one void
    outer, holes, _ = ap._shape_record(geo, 1)
    assert len(outer) == 3
    assert len(holes) == 1 and len(holes[0]) == 3
    assert abs(holes[0][0][0] - 10.0 * 0.0254) < 1e-6


def test_hole_corruption_guard():
    # a void with an absurd coordinate is dropped, not turned into garbage copper
    geo = _shape_geo([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)])
    geo += struct.pack("<I", 3) + struct.pack("<dd", 1e12, 1e12) \
        + struct.pack("<dd", 2e12, 1e12) + struct.pack("<dd", 2e12, 2e12)
    outer, holes, _ = ap._shape_record(geo, 1)
    assert len(outer) == 3
    assert holes == []          # corrupt hole discarded


def test_region_record_doubles():
    geo = struct.pack("<I", 2) + struct.pack("<dd", 27500000.0, 10050000.0) \
        + struct.pack("<dd", 31000000.0, 10050000.0)
    outer, holes, had_arc = ap._region_record(geo, 0)
    assert had_arc is False and holes == []
    assert abs(outer[0][0] - 2750.0 * 0.0254) < 1e-6   # 27500000/10000 mil -> mm


def test_records_framing():
    geo = _shape_geo([(0, 0), (10, 0), (10, 10), (0, 10)])
    prop = "|V7_LAYER=TOP|NAME= |KIND=0|SUBPOLYINDEX=0|"
    data = _record(_body(net=-1, poly=1, prop=prop, geo=geo)) * 2
    bodies = list(ap._records(data))
    assert len(bodies) == 2
    assert struct.unpack_from("<h", bodies[0], 5)[0] == 1   # poly index


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: altium_pour tests passed")
