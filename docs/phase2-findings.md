# Kitium Phase 2 — Findings (2026-06-16)

Built on `kicad/kicad:10.0.0-full` (3D models for render). `make gate` exits 0 on both
fixtures; outputs owned by the invoking user (container runs as `--user`).

## DRC violation histogram (eDP fixture, post-zone-refill, pre-filter)

1192 total. **Errors:** clearance 499, track_width 199, drill_out_of_range 178,
solder_mask_bridge 17, hole_clearance 12-14, starved_thermal 4, shorting_items 2,
tracks_crossing 1, unresolved_variable 1. **Warnings:** text_height 118,
lib_footprint_issues 112, silk_over_copper 33, silk_overlap 10, silk_edge_clearance 4,
track_dangling 1, nonmirrored_text_on_back_layer 1.

## Filtering decision

Filtered (import artifacts — board rules / net-classes don't import, DESIGN §11):
`clearance`, `track_width`, `drill_out_of_range`, `hole_clearance`,
`solder_mask_bridge`, `starved_thermal`, `unresolved_variable`.

**NOT filtered** (kept visible): `tracks_crossing` and `shorting_items` (real geometry
checks — though with `nets:0` they may themselves be import-related; assess on a real
board) and all `warning`-severity types.

**Post-filter gateable errors:** eDP **3** (shorting_items ×2, tracks_crossing ×1),
HiFive **0**. (Pre-filter eDP was 913 errors.)

### How filtering is detected

KiBot does NOT remove filtered violations from the DRC JSON — it annotates each with
`excluded: true` / `excluded_by_kibot: true` in place. `scripts/drc_gate.py` therefore
counts error-severity violations where `excluded` is falsy. This keeps the kibot config
the single source of truth for the filter list (no duplication in the gate script).

## Render

KiBot `render_3d` stays disabled (broken on KiCad 10, W143). Native
`kicad-cli pcb render` (isometric, `--quality high`, on the `-full` image) produces a
fully-populated 3D thumbnail (~1 MB PNG, ~5 s) for both fixtures. Best-effort: a render
failure logs a WARN and exits 0 — verified it never fails the gate.

## Gating

`block` mode now keys off the post-filter DRC error count
(`scripts/drc_gate.py` reading the DRC JSON), NOT KiBot's exit code (which is 0 under
`dont_stop`). Best-effort render/BOM failures never set `drc_failed`.

## Board BOM

`pcb_bom.py` now runs for every board unconditionally (112 components on each fixture).
The Altium cross-check (`bom_crosscheck.py`) still runs only when a `bom_csv` input is
supplied — that's Phase 4.

## Dev-loop

`make gate`/`spike` run the container as `--user $(id -u):$(id -g)` with `HOME=/tmp`,
so outputs are owned by the invoking user (no more root-owned files in the tree).
