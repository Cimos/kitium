#!/usr/bin/env python3
"""Tests for tools/compare/classify_layers.py — top-view layer picking across the
naming schemes we see: Altium extensions, KiBot-from-Altium names, KiCad canonical."""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "classify_layers", os.path.join(HERE, "..", "tools", "compare", "classify_layers.py"))
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def _touch(d, names):
    for n in names:
        open(os.path.join(d, n), "w").close()


def _names(d):
    return [os.path.basename(p) for p in cl.classify(d)]


def test_altium_extensions():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ["B.GTL", "B.GTO", "B.GTS", "B.GKO", "B.GBL", "B.GBO", "B.DRL"])
        # outline, copper, mask, silk — and no bottom-side layers
        assert _names(d) == ["B.GKO", "B.GTL", "B.GTS", "B.GTO"], _names(d)


def test_kibot_from_altium_names():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ["X-Edge_Cuts.gbr", "X-Top Layer.gbr", "X-Top Solder.gbr",
                   "X-Top Overlay.gbr", "X-Bottom Layer.gbr"])
        assert _names(d) == ["X-Edge_Cuts.gbr", "X-Top Layer.gbr",
                             "X-Top Solder.gbr", "X-Top Overlay.gbr"], _names(d)


def test_kicad_canonical():
    with tempfile.TemporaryDirectory() as d:
        _touch(d, ["x-Edge_Cuts.gbr", "x-F_Cu.gbr", "x-F_Mask.gbr",
                   "x-F_Silkscreen.gbr", "x-B_Cu.gbr"])
        got = _names(d)
        assert got == ["x-Edge_Cuts.gbr", "x-F_Cu.gbr", "x-F_Mask.gbr",
                       "x-F_Silkscreen.gbr"], got


if __name__ == "__main__":
    test_altium_extensions()
    test_kibot_from_altium_names()
    test_kicad_canonical()
    print("OK: classify_layers tests passed")
