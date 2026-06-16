# Kitium Phase 2 — Trustworthy Core Outputs (Design / Spec)

**Date:** 2026-06-16
**Status:** Proposed (awaiting review)
**Scope:** Phase 2 — make the converted-board gate *trustworthy*: filtered DRC, a
working render, a board-BOM artifact, and a gate decision that separates real
failures from best-effort ones.
**Parent design:** [`DESIGN.md`](../../../DESIGN.md) §5 (validation semantics), §6
(roadmap), §11 (import gotchas). **Builds on:** [`docs/phase0-findings.md`](../../phase0-findings.md).

---

## 1. Goal

Phase 0 proved the pipeline *produces* artifacts. Phase 2 makes those artifacts
*trustworthy*: DRC that surfaces real issues instead of 768 lines of import noise, a
3D render that actually renders, a board BOM emitted as a first-class artifact, and a
gate that blocks on real DRC failures while never blocking on best-effort renders.

## 2. Background (from Phase 0)

- DRC produced 768 violations, all confirmed import artifacts: `track_width`,
  `starved_thermal`, `solder_mask_bridge`, `drill_out_of_range`.
- `render_3d` (KiBot → KiAuto `pcbnew_do`) is broken on KiCad 10 (W143); disabled.
- `dont_stop: true` makes KiBot exit 0 even with DRC violations, so the entrypoint's
  `kibot_rc != 0 → drc_failed` logic can no longer detect DRC failure, and a failed
  best-effort render would wrongly trip it.
- `pcb_bom.py` exists and extracts Reference/Value/Footprint, but never runs in the
  gate (only fires when a `bom_csv` input is present).

## 3. Decisions (confirmed)

- **DRC:** filter the 4 confirmed import-artifact types; keep DRC **informational**
  (never blocking yet). Promotion to a gate is a later tuning step (DESIGN §5).
- **Render:** native `kicad-cli pcb render` (no GUI/Xvfb/Blender), called outside
  KiBot. Requires the `-full` image for 3D models. Best-effort, never a gate.
- **Scope:** DRC filters + render + always-on board BOM + gating fix + dev-loop
  hardening. **Defer:** diff PDF (Phase 3, needs PR base ref), BOM cross-check
  (Phase 4), `.PrjPcb` auto-detect (minor).

## 4. Components & changes

### 4.1 DRC filtering — `kibot/kitium.kibot.yaml`
Add a `filters` list under the `drc:` preflight, one entry per confirmed type:

```yaml
  drc:
    enabled: true
    dont_stop: true
    schematic_parity: false
    ignore_unconnected: true
    format: [HTML, RPT, JSON]   # JSON added for drc_gate.py
    dir: drc
    filters:
      - filter: "Altium import: board min track width not imported (gitlab #15584)"
        error: track_width
        change_to: ignore
      - filter: "Altium import: zone refill thermal-spoke artifact"
        error: starved_thermal
        change_to: ignore
      - filter: "Altium import: solder-mask bridge from lost net connectivity"
        error: solder_mask_bridge
        change_to: ignore
      - filter: "Altium import: drill size vs un-imported board constraint"
        error: drill_out_of_range
        change_to: ignore
```

Each `filter` string documents *why the violation is an import artifact, not a real
defect*. We never filter by broad regex — only the named `error` ids confirmed in
Phase 0. New/unknown violation types remain visible.

### 4.2 Render — new `scripts/render_board.sh`
- Invoked by `entrypoint.sh` per board, in a best-effort block (`|| warn`).
- Runs `kicad-cli pcb render --output <docs>/<name>-3d.png <board>` (+ a sensible
  default side/quality). Failure logs a warning and sets **no** gate flag.
- `render_3d` stays disabled in the KiBot config (superseded).
- Base image → `kicad/kicad:10.0.0-full` in `Dockerfile` (`ARG`) and `Makefile`
  (`BASE`) so 3D models are present. Document the larger-image / CI-pull trade-off.

### 4.3 Board BOM always generated — `scripts/entrypoint.sh`
- Always run `pcb_bom.py <board> --out <bdir>/board-bom.csv` for every board,
  independent of whether `bom_csv` is supplied.
- Cross-check (`bom_crosscheck.py`) still runs **only** when `bom_csv` is given
  (unchanged; that's Phase 4). Report links the board-BOM artifact.

### 4.4 Gating fix — new `scripts/drc_gate.py` + `entrypoint.sh`
- `drc_gate.py` reads the KiBot DRC **JSON** report and prints the post-filter
  violation count (errors, excluding `ignore`d), exiting non-zero if > 0.
- `entrypoint.sh`:
  - Stop using generic `kibot_rc` as the DRC signal. Instead call `drc_gate.py` on
    the per-board DRC JSON to compute `drc_failed`.
  - Run `render_board.sh` as a separate best-effort step that can never set
    `drc_failed` or otherwise affect the gate.
  - `block` mode hard-fails only when the post-filter DRC count > 0 (or conversion /
    pre-flight fails, unchanged). Best-effort render/BOM failures are warnings.

### 4.5 Dev-loop hardening — `Makefile`
- `make gate`/`make spike` run the container with `--user $(id -u):$(id -g)` so
  outputs are owned by the invoking user, not root (fixes the root-owned-tree cleanup
  pain). Verify KiCad/KiBot still run as non-root in the container; if a step needs a
  writable HOME, set `-e HOME=/tmp`.

## 5. Data flow (per board, unchanged shape)

```
convert.sh → refill_zones.py → pcb_inspect.py --assert
  → kibot (gerbers, drill, position, pdf, DRC[filtered, JSON])
  → drc_gate.py (post-filter count → drc_failed)        # gateable
  → render_board.sh (kicad-cli render PNG)               # best-effort, never gates
  → pcb_bom.py (board-bom.csv)                           # always
  → [bom_crosscheck.py only if bom_csv given]            # Phase 4
report.md ← metrics + DRC count + artifact links
gate: hard-fail on conversion/pre-flight always; on DRC count only in block mode
```

## 6. Testing / verification

- `make image` builds on `-full`; `make test` (shellcheck + py_compile) clean,
  including the two new scripts.
- `make gate` on the eDP + HiFive fixtures:
  - DRC report shows the 4 artifact types **filtered out**; post-filter count
    reported per board.
  - `<name>-3d.png` render produced for at least one board (best-effort; a failure is
    logged, not fatal).
  - `board-bom.csv` produced for every board with sane component counts (~112 rows,
    matching Phase 0 refdes counts).
  - Gate exits 0 in `report` mode. In `block` mode, exits non-zero **only** because of
    the post-filter DRC count — never because of a render failure (test by forcing a
    render failure and confirming the gate still passes in report mode).
- Unit-test the pure-Python pieces (`drc_gate.py` parse) with a small fixture JSON.

## 7. Exit criteria

1. DRC report on both fixtures shows the 4 confirmed types filtered; a post-filter
   violation count is computed and surfaced.
2. A 3D render PNG is produced for the eDP board via `kicad-cli pcb render`.
3. `board-bom.csv` is generated for every board, always.
4. The gate's `block` decision is driven by the post-filter DRC count; a forced render
   failure does **not** fail the gate.
5. `make gate` runs as the invoking user (no root-owned output files); `make test` clean.

## 8. Out of scope (deferred)

Diff PDF / PR base-ref plumbing (Phase 3); BOM cross-check vs Altium CSV (Phase 4);
`.PrjPcb` auto-detect enumeration (minor); promoting DRC to a default hard gate
(tuning, after real-board output); GHCR `docker://` packaging (Phase 5).

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| KiCad violation `error` ids differ from the names in logs | Confirm exact ids from the Phase 0 DRC JSON before finalizing filters; adjust. |
| `kicad-cli pcb render` also fragile on KiCad 10 | It's best-effort by design; a failure is logged, never gates. Fall back to PDFs as the visual aid. |
| `-full` image slows CI pull | Acceptable for the dev loop; Phase 5 can reconsider a slimmer image if renders move to a separate job. |
| Over-filtering hides a real defect | Filter only by confirmed `error` id (never broad regex); each filter documents its justification; unknown types stay visible. |
| `--user` breaks a container step needing writable HOME | Set `-e HOME=/tmp`; verify in `make gate`. |
