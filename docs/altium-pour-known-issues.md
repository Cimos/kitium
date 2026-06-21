# Altium pour import — known issues (UNFINISHED)

**Status: work in progress. Do NOT treat `scripts/altium_pour.py` (PR #7) as finished.**

The exact-pour importer reads Altium's stored poured copper from the `.PcbDoc`
(`ShapeBasedRegions6` / `Regions6`) and injects it as each KiCad zone's locked fill, instead of
re-pouring. It is opt-in/best-effort and falls back to the KiCad re-pour on failure, so it does not
break the gate — but the imported copper is **not yet a faithful match to the published gerbers**.

## Open issue: copper differs from the published gerbers

Side-by-side renders of imported copper vs the project's published Altium gerbers show real
**copper differences**, most visible on **inner layers**. On `DM1090FFC` (4-layer) the inner layer
(MID1 / `.G1`) pour shape, void pattern and island layout do not match the published gerber; the
top layer also differs in places. Other boards look closer on the top layer but have not been
verified per-layer in detail.

An earlier status note claimed the importer was "validated faithful across 6 boards." **That was
over-stated** — it was based on coarse, full-board top-layer views. Treat the importer as producing
an *approximate* pour that still needs work before it can be trusted as exact.

## What currently works

- Parses `ShapeBasedRegions6` region records (37-byte outer-ring vertices) with a `Regions6`
  double-vertex fallback.
- Subtracts void contours (count at record body offset 14; 16-byte double vertices after the outer
  ring) and fractures the polygon set so voids survive save/plot (without this the pour filled solid).
- Resolves net via the parent polygon → `Nets6`; maps Altium layers to KiCad layer IDs
  (TOP/BOTTOM/MIDn/PLANEn); derives the per-board coordinate transform (offset + Y-flip) from a
  zone outline matched to its Altium polygon.
- Restricts import to copper layers; drops corrupt void contours; falls back to re-pour on
  transform failure / no regions / corrupt data.

## What still needs investigating / fixing

- **Inner-layer copper mismatch** (primary). Determine why MID-layer pours differ: candidates —
  missing or extra region records, incomplete hole-contour grouping (multiple voids per region,
  `UNIONINDEX`/`SUBPOLYINDEX`), per-layer transform error, or regions whose voids are encoded
  differently from the cases handled so far.
- **Top-layer residual differences** on some boards — characterise and quantify (a registered
  per-layer diff vs published, not eyeballing).
- **Verify per-layer, not just top**, on every test board before claiming fidelity.
- **Edge.Cuts / board outline**: internal cutouts/keepout rectangles render differently — this is
  kicad-cli's import (not `altium_pour`), but it confounds visual comparisons; isolate copper-only.
- Consider a **fidelity check that auto-detects mismatch** (e.g. compare imported fill area /
  region count against expectation) and falls back to re-pour when the import is clearly off.

## How to reproduce a comparison

For a board with published gerbers (`.GTL` top, `.G1`/`.G2` inner, `.GBL` bottom, `.GKO` outline):

```
kicad-cli pcb import --format altium --output b.kicad_pcb board.PcbDoc
python3 scripts/altium_rules.py board.PcbDoc --apply b.kicad_pcb
python3 scripts/altium_pour.py board.PcbDoc --apply b.kicad_pcb      # exit 0 = imported, 3 = fell back
kicad-cli pcb export gerbers --layers "F.Cu,In1.Cu,B.Cu,Edge.Cuts" -o g/ b.kicad_pcb
# render each KiCad layer and the matching published gerber (e.g. with gerbv, copper + outline)
# and compare per layer. `altium_pour.py board.PcbDoc --dump` lists regions/voids per polygon.
```

Public OAK Altium boards with published gerbers (used so far) live under the Luxonis hardware
repos; `DM1090FFC` is a good 4-layer reproducer for the inner-layer mismatch.
