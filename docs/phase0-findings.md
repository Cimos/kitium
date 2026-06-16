# Kitium Phase 0 — Findings (2026-06-16)

De-risk spike run on WSL2 (Ubuntu 24.04, Docker Engine 29.5.3) against KiCad's own
Altium importer fixtures: `eDP_adapter_dvt1` (115 footprints) and `HiFive1.B01`
(116 footprints). **Result: the clean-CLI core works end-to-end; `make gate` exits 0
with full fab artifacts for both boards.**

## Pinned base image

`kicad/kicad:10.0.0` (avoided `10.0.1` render/STEP regression). `10.0.0-full` was
tested for `render_3d` but did **not** fix it (see below), so we kept the lean image.

## Dockerfile fixes required (KiBot on KiCad 10)

The make-or-break question — *does KiBot work on KiCad 10?* — is **YES**, but the
bare `pip install kibot` was broken in three ways, each found only by a real run:

1. **`pip install --no-compile`** — without it, KiBot's macro/plugin system fails:
   `cannot import name 'macros' from 'kibot.macros'`. KiBot pre-compiled `.pyc` files
   shadow the modules it rewrites at import time. (KiBot's own error advises this.)
2. **`python3-lxml`** (apt) — `pip install kibot` does **not** pull in lxml, but
   KiBot's plugin loader needs it to even bootstrap (`No module named 'lxml'`).
3. **`xvfb`** (apt) — KiBot runs `run_drc`, `pdf_pcb_print`, and `render_3d` via
   **KiAuto's `pcbnew_do` GUI driver**, not pure `kicad-cli`. KiAuto needs an X
   virtual framebuffer. (Correction to DESIGN.md §12, which assumed DRC/renders were
   pure CLI.)

After these, `kibot --version` + `import pcbnew` report KiCad `10.0.0` cleanly.

## KiBot config fixes required

`run_drc: true` (legacy boolean preflight) aborts the **entire** KiBot run on DRC
errors, so no artifacts were produced. Replaced with the modern `drc:` preflight:

- `dont_stop: true` — DRC stays informational; gerbers/pdf still generate (DESIGN §5).
- `schematic_parity: false` — board-only import has no schematic to compare against.
- `ignore_unconnected: true` — Altium net info doesn't import (see `nets: 0` below).

`render_3d` set to `run_by_default: false` — see below.

## §7 open questions — resolved

- **[x] Exact `pcb import` flag syntax on the pinned image:** Confirmed working —
  `kicad-cli pcb import --format altium --output <out> --report-format json
  --report-file <f> <input>`. Unmapped Altium "Internal Plane" layers emit non-fatal
  warnings (14 on the eDP board) — the §11 lossy layer-mapping reality.
- **[x] Does KiBot support KiCad 10's `pcbnew` API?** YES (KiBot 1.9.0), given the
  three Dockerfile fixes above. The DESIGN §6 "else pin KiCad 9" fork is **not** taken.
- **[~] Which component fields survive PcbDoc → KiCad import?** Footprints, refdes,
  values survive (**112 refs, 0 UNK** — the §11 UNK-refdes regression does NOT bite
  this version). **Nets do NOT import (`nets: 0`)** — connectivity/net-class info is
  lost (gitlab #15584). Full board-BOM field audit deferred to Phase 4.
- **[ ] Consuming-repo `.PrjPcb`/`.PcbDoc` location convention:** Not testable with
  fixtures — org policy decision, still open.
- **[ ] Altium BOM CSV column names:** Not testable with fixtures (no Altium BOM
  export present) — deferred to Phase 4 with a real export.

## Artifacts observed (per board, `make gate`)

| Output | eDP | HiFive | Notes |
|---|---|---|---|
| Gerbers (`.gbr`) | 29 | 32 | all layers incl. mapped inner planes |
| Drill (`.drl`) | 1 | 1 | |
| Position CSV | 2 | 2 | top + bottom |
| Layer PDFs | 29 | 32 | |
| DRC report (HTML/RPT/txt) | ✓ | ✓ | informational |
| 3D render PNG | ✗ | ✗ | **disabled** — see below |

## DRC is noisy by design (confirmed)

768 DRC errors on the eDP board, all import artifacts: `track_width` (board min-width
constraints didn't import → every trace looks too thin), `starved_thermal`,
`solder_mask_bridge`, `drill_out_of_range`. **Phase 2** must add KiBot `drc.filters`
to suppress confirmed false positives before DRC can become a gate (DESIGN §5, §11).

## Surprises / follow-ups for Phase 1+

- **`render_3d` is broken on KiCad 10** — KiBot's `render_3d` wraps KiAuto `pcbnew_do`,
  which returns 1 (KiBot warns W143 "use blender_export instead"). The `-full` image's
  3D models do **not** fix it. **Phase 2:** swap to native `kicad-cli pcb render` or
  `blender_export`. Renders stay best-effort, never a gate (DESIGN §5/§11/§12).
- **Gating bug to fix (Phase 2/3):** `entrypoint.sh` treats *any* non-zero KiBot exit
  as `drc_failed`, so a failed best-effort render would wrongly count toward a
  `block`-mode gate. Separate "render failed" (never blocks) from "DRC failed".
- **`xvfb` is needed for the v1 core**, not just the deferred schematic/GUI track —
  correct DESIGN §12's "clean CLI" classification of DRC/pdf/render.
- Zones import unfilled — confirmed (`refill_zones.py` refilled 101 / 39 zones).
  Guard is doing its job.
