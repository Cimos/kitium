#!/usr/bin/env python3
"""Build a self-contained HTML comparison page: Kitium's converted board vs the
published reference gerbers, side by side, plus the 3D render and a metrics table.

Images are embedded as base64 so the page is a single portable file.

Usage:
    build_page.py --board NAME --kitium-png a.png --ref-png b.png \
        [--render-png c.png] [--metrics metrics.json] --out compare.html
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os


def _img(path):
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def _metrics_rows(metrics_path):
    if not metrics_path or not os.path.isfile(metrics_path):
        return ""
    try:
        m = json.load(open(metrics_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    keys = ["footprints", "tracks", "vias", "zones", "nets",
            "references_total", "references_unk"]
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(m[k]))}</td></tr>"
        for k in keys if k in m)
    return f"<table><tr><th>Metric</th><th>Value</th></tr>{rows}</table>"


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kitium compare — {board}</title>
<style>
 :root{{--bg:#0b0f0e;--surface:#141a18;--text:#f4f1e8;--muted:#8f8a7e;--accent:#e8a33d;--border:#262d2a}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);
   font:15px/1.5 system-ui,sans-serif;padding:2rem;max-width:1100px;margin:0 auto}}
 h1{{color:var(--accent);font-size:1.3rem}} h2{{font-size:1.05rem;margin-top:1.6rem}}
 .cmp{{display:flex;gap:1rem;flex-wrap:wrap}} figure{{flex:1;min-width:320px;margin:0}}
 figcaption{{color:var(--muted);margin-bottom:.3rem}}
 img{{width:100%;border:1px solid var(--border);border-radius:6px;background:#000}}
 img.r3{{max-width:520px}}
 table{{width:100%;border-collapse:collapse;margin-top:.5rem}}
 td,th{{text-align:left;padding:.3rem .5rem;border-bottom:1px solid var(--border)}}
 .meta{{color:var(--muted);font-size:.85rem}}
</style></head><body>
<h1>Kitium fidelity compare — {board}</h1>
<p class="meta">Left: the project's published Altium gerbers. Right: Kitium's
Altium&rarr;KiCad conversion, re-exported to gerbers. Same top-side layers, rendered the
same way, so geometry differences are visible at a glance.</p>
<h2>Top view</h2>
<div class="cmp">
  <figure><figcaption><b>Published</b> (their gerbers)</figcaption><img src="{ref}"></figure>
  <figure><figcaption><b>Kitium</b> (converted)</figcaption><img src="{kit}"></figure>
</div>
{render_block}
<h2>Converted-board metrics</h2>
{metrics}
<p class="meta">nets=0 is expected — connectivity doesn't survive the KiCad import; this is
a board-geometry fidelity check.</p>
</body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--kitium-png", required=True)
    ap.add_argument("--ref-png", required=True)
    ap.add_argument("--render-png")
    ap.add_argument("--metrics")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    r3 = _img(args.render_png)
    render_block = (f'<h2>Kitium 3D render</h2><img class="r3" src="{r3}">' if r3 else "")
    page = PAGE.format(
        board=html.escape(args.board),
        ref=_img(args.ref_png), kit=_img(args.kitium_png),
        render_block=render_block, metrics=_metrics_rows(args.metrics),
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
