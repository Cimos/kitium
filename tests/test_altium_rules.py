#!/usr/bin/env python3
"""Tests for scripts/altium_rules.py parsing (the pure functions — no olefile/pcbnew)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "altium_rules", os.path.join(HERE, "..", "scripts", "altium_rules.py"))
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)


def test_to_mm():
    assert abs(ar._to_mm("3mil") - 0.0762) < 1e-6
    assert ar._to_mm("0.2mm") == 0.2
    assert ar._to_mm("10mil") and abs(ar._to_mm("10mil") - 0.254) < 1e-6
    assert ar._to_mm("") is None


def test_parse_polygons_takes_tightest_min_width():
    text = ("|SELECTION=FALSE|POLYGONTYPE=Polygon|REMOVEDEAD=TRUE|MINPRIMLENGTH=5mil|VX0=1mil"
            "|SELECTION=FALSE|POLYGONTYPE=Polygon|REMOVEDEAD=FALSE|MINPRIMLENGTH=3mil|VX0=2mil")
    p = ar.parse_polygons(text)
    assert abs(p["pour_min_width_mm"] - 0.0762) < 1e-6   # min(5,3) mil
    assert p["remove_dead_copper"] is True
    assert p["polygon_count"] == 2


def test_parse_rules_clearance_and_width():
    text = ("|SELECTION=FALSE|RULEKIND=Clearance|NAME=Clearance|GAP=10mil|ENABLED=TRUE"
            "|SELECTION=FALSE|RULEKIND=Width|NAME=Width|MINLIMIT=6mil|MAXLIMIT=20mil"
            "|SELECTION=FALSE|RULEKIND=PolygonConnect|NAME=PC|CONNECTSTYLE=Direct|RELIEFENTRIES=4")
    r = ar.parse_rules(text)
    assert "Clearance" in r["kinds"] and "Width" in r["kinds"]
    assert abs(r["min_clearance_mm"] - 0.254) < 1e-6     # 10 mil
    assert abs(r["min_track_width_mm"] - 0.1524) < 1e-6  # 6 mil
    assert r["pad_connect"] == "Direct"


def test_parse_rules_empty():
    r = ar.parse_rules("")
    assert r["min_clearance_mm"] is None and r["kinds"] == []


if __name__ == "__main__":
    test_to_mm()
    test_parse_polygons_takes_tightest_min_width()
    test_parse_rules_clearance_and_width()
    test_parse_rules_empty()
    print("OK: altium_rules tests passed")
