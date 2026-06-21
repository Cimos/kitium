# Kitium Phase 2 — Trustworthy Core Outputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the converted-board gate trustworthy — filter import-noise DRC, render via native `kicad-cli`, always emit a board BOM, and drive the block decision off the post-filter DRC count instead of KiBot's exit code.

**Architecture:** KiBot keeps producing gerbers/drill/position/pdf and an (informational) DRC report, now with `drc.filters` that ignore the seven confirmed Altium-import artifact violation types and a `JSON` report format. A new `drc_gate.py` reads that JSON for the post-filter error count, which `entrypoint.sh` uses for `block` mode. Renders move out of KiBot to a best-effort `kicad-cli pcb render` step that can never gate. The board BOM is always generated.

**Tech Stack:** Bash, Python 3 stdlib, KiBot 1.9.0, `kicad/kicad:10.0.0-full` (3D models for render), Docker, GNU Make, shellcheck.

**Spec:** [`docs/superpowers/specs/2026-06-16-kitium-phase2-design.md`](../specs/2026-06-16-kitium-phase2-design.md)

> **Conventions:** Commands run from the repo root. Docker commands assume the
> `sg docker -c "..."` wrapper on this WSL2 box (the shell isn't in the `docker`
> group yet). "Tests" for shell are `shellcheck`; for Python, a plain-assert script
> under `tests/` plus `py_compile` — the repo has no pytest, and we don't add it.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `Dockerfile` | Modify (`ARG`) | Base image → `-full` (3D models for render) |
| `Makefile` | Modify (`BASE`, gate/spike runs) | `-full` base; run container as invoking user |
| `kibot/kitium.kibot.yaml` | Modify (`drc` preflight) | Add `filters` (7 types) + `JSON` format; render_3d stays off |
| `scripts/drc_gate.py` | Create | Count post-filter gateable DRC violations from the JSON report |
| `scripts/render_board.sh` | Create | Best-effort `kicad-cli pcb render` PNG |
| `scripts/entrypoint.sh` | Modify | Always BOM; best-effort render; gate via `drc_gate.py` |
| `tests/test_drc_gate.py` | Create | Unit test for `drc_gate.py` parsing/exit |
| `DESIGN.md` | Modify (§5/§12) | Record Phase 2 reality (filters, render path, xvfb) |
| `docs/phase2-findings.md` | Create | DRC type histogram + decisions |

---

## Task 1: Switch to the `-full` image and run the container as the invoking user

**Files:**
- Modify: `Dockerfile:10`
- Modify: `Makefile:11` (`BASE`), `Makefile:13` (`DRUN`), `Makefile:34-39` (`gate`)

- [ ] **Step 1: Point the Dockerfile base at `-full`**

In `Dockerfile`, change line 10:
```dockerfile
ARG KICAD_IMAGE=kicad/kicad:10.0.0
```
to:
```dockerfile
ARG KICAD_IMAGE=kicad/kicad:10.0.0-full
```

- [ ] **Step 2: Update the Makefile base and run-as-user wiring**

In `Makefile`, change line 11:
```makefile
BASE  ?= kicad/kicad:10.0.0   # pinned: 10.0.0 known-good; AVOID 10.0.1 (render regression)
```
to:
```makefile
BASE  ?= kicad/kicad:10.0.0-full   # -full ships 3D models for kicad-cli render; AVOID 10.0.1
```

Change line 13 (`DRUN`) from:
```makefile
DRUN  := docker run --rm -v $(PWD):/work -w /work --entrypoint bash $(IMAGE)
```
to (run as the invoking user so outputs aren't root-owned; `HOME=/tmp` gives a
writable home for KiCad/KiBot config):
```makefile
USERFLAGS := --user $(shell id -u):$(shell id -g) -e HOME=/tmp
DRUN  := docker run --rm $(USERFLAGS) -v $(PWD):/work -w /work --entrypoint bash $(IMAGE)
```

In the `gate` target, add `$(USERFLAGS)` to its `docker run`:
```makefile
gate: fixtures image
	docker run --rm $(USERFLAGS) -v $(PWD):/work -w /work \
	  -e INPUT_BOARDS_GLOB='fixtures/**/*.PcbDoc' \
	  -e INPUT_DRC=report \
	  -e INPUT_OUTPUT_DIR=fixtures/kitium-out \
	  $(IMAGE)
```

- [ ] **Step 3: Build the image**

Run: `sg docker -c "make image"`
Expected: build succeeds on `kicad/kicad:10.0.0-full`.

- [ ] **Step 4: Verify the container runs as the invoking user (no root-owned outputs)**

Run: `sg docker -c "make spike"`
Then: `find fixtures/out -newer Makefile -printf '%u\n' | sort -u`
Expected: prints only your username (not `root`); spike still passes `--assert`.
If KiCad errors about HOME/permissions, confirm `HOME=/tmp` is set in `USERFLAGS`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile Makefile
git commit -m "Phase 2: -full base image for renders; run dev container as invoking user"
```

---

## Task 2: Add DRC filters + JSON report to the KiBot config

**Files:**
- Modify: `kibot/kitium.kibot.yaml` (the `drc:` preflight block)

Filter the seven confirmed Altium-import artifact error types. **Do NOT filter
`tracks_crossing`** (geometry, not a missing-constraint artifact — could be a real
defect) or any `warning`-severity type (warnings never gate). Counts observed on the
eDP fixture: clearance 499, track_width 199, drill_out_of_range 178, solder_mask_bridge
17, hole_clearance 14, starved_thermal 4, unresolved_variable 1.

- [ ] **Step 1: Replace the `drc:` preflight block**

In `kibot/kitium.kibot.yaml`, replace the existing `drc:` block under `preflight:`
with (note `format` gains `JSON`, and the `filters` list):
```yaml
  drc:
    enabled: true
    dont_stop: true            # keep generating gerbers/pdf/render even if DRC errors
    schematic_parity: false    # board-only import: there is no schematic to compare
    ignore_unconnected: true   # Altium net info doesn't import (gitlab #15584) -> nets=0
    format: [HTML, RPT, JSON]  # JSON is read by scripts/drc_gate.py for the gate count
    dir: drc
    # Suppress CONFIRMED Altium-import artifacts (Phase 0/2). Each is noise because
    # board design rules + net-class membership don't import (DESIGN.md §11), so every
    # clearance/width/drill check fires against KiCad defaults. We filter by exact
    # violation `error` id only — never broad regex — so genuine/new types stay visible.
    # NOT filtered: tracks_crossing (real geometry) and all warning-severity types.
    filters:
      - filter: "Altium import: clearances use KiCad defaults (net-class not imported, gitlab #15584)"
        error: clearance
        change_to: ignore
      - filter: "Altium import: board min track width not imported (gitlab #15584)"
        error: track_width
        change_to: ignore
      - filter: "Altium import: hole/drill size vs un-imported board constraint"
        error: drill_out_of_range
        change_to: ignore
      - filter: "Altium import: hole clearance vs un-imported board constraint"
        error: hole_clearance
        change_to: ignore
      - filter: "Altium import: solder-mask bridge from lost net connectivity (nets=0)"
        error: solder_mask_bridge
        change_to: ignore
      - filter: "Altium import: zone refill thermal-spoke artifact"
        error: starved_thermal
        change_to: ignore
      - filter: "Altium import: unresolved Altium text variable"
        error: unresolved_variable
        change_to: ignore
```

- [ ] **Step 2: Build the image (config is COPYd in) and run the gate**

Run: `sg docker -c "make image" && sg docker -c "make gate"`
Expected: exits 0 (report mode).

- [ ] **Step 3: Verify the filters dropped the error count**

Run:
```bash
python3 -c "import json,glob,collections; \
f=glob.glob('fixtures/kitium-out/build/eDP_adapter_dvt1/out/drc/*.json')[0]; \
v=json.load(open(f))['violations']; \
c=collections.Counter((x['type'],x['severity']) for x in v); \
print('errors:', sum(n for (t,s),n in c.items() if s=='error')); \
[print(n,s,t) for (t,s),n in c.most_common()]"
```
Expected: error count drops from ~912 to a small residual (the lone `tracks_crossing`
error remains; the seven filtered types no longer appear as errors). If a filtered
type still shows as `error`, the `error:` id is wrong — fix it against the printed type.

- [ ] **Step 4: Commit**

```bash
git add kibot/kitium.kibot.yaml
git commit -m "Phase 2: filter confirmed Altium-import DRC artifacts; add JSON report"
```

---

## Task 3: `drc_gate.py` — count post-filter gateable violations (TDD)

**Files:**
- Create: `scripts/drc_gate.py`
- Create: `tests/test_drc_gate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_drc_gate.py`:
```python
#!/usr/bin/env python3
"""Plain-assert unit tests for scripts/drc_gate.py (no pytest dependency)."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "scripts", "drc_gate.py")


def _run(report: dict, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(report, fh)
        path = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, GATE, path, *args],
            capture_output=True, text=True,
        )
        return proc
    finally:
        os.unlink(path)


def test_counts_only_unexcluded_error_severity():
    # KiBot annotates filtered violations with excluded=true IN PLACE (it does not
    # remove them from the raw KiCad JSON). The gate must ignore those.
    report = {"violations": [
        {"type": "tracks_crossing", "severity": "error"},
        {"type": "clearance", "severity": "error", "excluded": True},  # filtered -> ignore
        {"type": "silk_overlap", "severity": "warning"},
    ]}
    proc = _run(report)
    assert proc.returncode == 1, proc.stderr
    assert "gateable error violations: 1" in proc.stdout, proc.stdout


def test_clean_report_exits_zero():
    report = {"violations": [{"type": "silk_overlap", "severity": "warning"}]}
    proc = _run(report)
    assert proc.returncode == 0, proc.stderr
    assert "gateable error violations: 0" in proc.stdout, proc.stdout


def test_missing_violations_key_is_clean():
    proc = _run({"unconnected_items": []})
    assert proc.returncode == 0, proc.stderr


if __name__ == "__main__":
    test_counts_only_unexcluded_error_severity()
    test_clean_report_exits_zero()
    test_missing_violations_key_is_clean()
    print("OK: drc_gate tests passed")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 tests/test_drc_gate.py`
Expected: FAIL (the subprocess can't find `scripts/drc_gate.py` → non-zero return, assertion error).

- [ ] **Step 3: Implement `scripts/drc_gate.py`**

Create `scripts/drc_gate.py`:
```python
#!/usr/bin/env python3
"""Count gateable DRC violations in a KiBot/KiCad DRC JSON report.

KiBot's `drc` preflight (format JSON) emits KiCad's native DRC JSON:
  {"violations": [{"type","severity","description","items"}, ...],
   "unconnected_items": [...], "schematic_parity": [...], ...}

KiBot applies `drc.filters` (change_to: ignore) by annotating each filtered violation
with `excluded: true` IN PLACE — it does NOT remove them from this raw KiCad JSON. So
the gateable count = error-severity violations that are NOT excluded. That's the signal
entrypoint.sh uses to decide `block` mode. Renders/BOM never reach this path.

Usage:
    drc_gate.py <drc.json> [--severity error] [--summary-out summary.txt]
Prints the count (and a per-type breakdown); exits 1 if count > 0, else 0.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys


def gateable(report: dict, severity: str) -> list:
    return [
        v for v in report.get("violations", [])
        if v.get("severity") == severity and not v.get("excluded")
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Count gateable DRC violations.")
    ap.add_argument("report")
    ap.add_argument("--severity", default="error")
    ap.add_argument("--summary-out")
    args = ap.parse_args(argv)

    with open(args.report, encoding="utf-8") as fh:
        report = json.load(fh)

    viol = gateable(report, args.severity)
    by_type = collections.Counter(v.get("type", "?") for v in viol)
    breakdown = "\n".join(f"{n}\t{t}" for t, n in by_type.most_common())

    print(f"gateable {args.severity} violations: {len(viol)}")
    if breakdown:
        print(breakdown)

    if args.summary_out:
        with open(args.summary_out, "w", encoding="utf-8") as fh:
            fh.write(f"Post-filter DRC {args.severity} violations: {len(viol)}\n")
            if breakdown:
                fh.write(breakdown + "\n")

    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 tests/test_drc_gate.py`
Expected: `OK: drc_gate tests passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/drc_gate.py tests/test_drc_gate.py
git commit -m "Phase 2: drc_gate.py — post-filter DRC violation count for the gate"
```

---

## Task 4: `render_board.sh` — best-effort native render

**Files:**
- Create: `scripts/render_board.sh`

- [ ] **Step 1: Implement `scripts/render_board.sh`**

Create `scripts/render_board.sh`:
```bash
#!/usr/bin/env bash
# Best-effort 3D render of a converted board via native kicad-cli (KiCad 10).
# Replaces KiBot's render_3d (KiAuto/pcbnew_do), which is broken on KiCad 10 (W143).
# NEVER gates: always exits 0; a render failure is a logged warning, not an error.
# 3D component models come from the -full base image.
set -uo pipefail

board="${1:?usage: render_board.sh <board.kicad_pcb> <out.png>}"
out="${2:?usage: render_board.sh <board.kicad_pcb> <out.png>}"
mkdir -p "$(dirname "${out}")"

# Isometric-ish perspective, opaque background, high quality — a PR thumbnail.
if kicad-cli pcb render \
     --output "${out}" \
     --width 1600 --height 1200 \
     --background opaque \
     --quality high \
     --perspective \
     --rotate '-25,0,-45' \
     "${board}"; then
  echo "[kitium] rendered: ${out}"
else
  echo "[kitium] WARN: render failed for ${board} (best-effort, not gating)" >&2
fi
exit 0
```

- [ ] **Step 2: Make it executable and shellcheck it**

Run: `chmod +x scripts/render_board.sh && sg docker -c "docker run --rm -v \"$PWD:/mnt\" -w /mnt koalaman/shellcheck:stable scripts/render_board.sh"`
Expected: exit 0 (no findings).

- [ ] **Step 3: Verify it renders a real board**

Run:
```bash
sg docker -c "docker run --rm --user \$(id -u):\$(id -g) -e HOME=/tmp -v \"$PWD:/work\" -w /work --entrypoint bash kitium:dev -c 'kicad-cli pcb import --format altium --output /tmp/b.kicad_pcb fixtures/eDP_adapter_dvt1_source/eDP_adapter_dvt1.PcbDoc >/dev/null 2>&1 && bash scripts/render_board.sh /tmp/b.kicad_pcb /work/fixtures/render-test.png'"
ls -la fixtures/render-test.png
```
Expected: `[kitium] rendered: ...` and a non-empty PNG (> 10 KB). If render fails,
the script still exits 0 and prints the WARN — acceptable (best-effort), but note it
in `docs/phase2-findings.md`.

- [ ] **Step 4: Commit**

```bash
git add scripts/render_board.sh
git commit -m "Phase 2: render_board.sh — best-effort kicad-cli 3D render"
```

---

## Task 5: Wire entrypoint — always BOM, best-effort render, gate via drc_gate

**Files:**
- Modify: `scripts/entrypoint.sh` (KiBot run block, BOM block, gate decision)

- [ ] **Step 1: Replace the KiBot-result handling with a drc_gate-based signal**

In `scripts/entrypoint.sh`, find the block that runs KiBot and sets `drc_failed`
(currently):
```bash
  set +e
  kibot -c "${KIBOT_CFG}" -b "${board}" -d "${bdir}/out" 2>&1 | tee -a "${bdir}/kibot.log"
  kibot_rc=${PIPESTATUS[0]}
  set -e
  [ "${kibot_rc}" -eq 0 ] || { warn "KiBot reported issues for ${name} (rc=${kibot_rc}) — see kibot.log"; drc_failed=1; }
```
Replace with (KiBot exit is now informational; the gate signal comes from the
post-filter DRC JSON via `drc_gate.py`):
```bash
  set +e
  kibot -c "${KIBOT_CFG}" -b "${board}" -d "${bdir}/out" 2>&1 | tee -a "${bdir}/kibot.log"
  kibot_rc=${PIPESTATUS[0]}
  set -e
  [ "${kibot_rc}" -eq 0 ] || warn "KiBot exited non-zero for ${name} (rc=${kibot_rc}) — see kibot.log (DRC dont_stop is expected)"

  # Gate signal: count POST-FILTER DRC errors from the JSON report (not kibot's rc,
  # which is 0 under dont_stop). Missing report = can't verify -> treat as failure.
  drc_json="$(ls "${bdir}/out/drc/"*.json 2>/dev/null | head -1 || true)"
  if [ -n "${drc_json}" ]; then
    set +e
    python3 "${SCRIPTS}/drc_gate.py" "${drc_json}" --summary-out "${bdir}/drc-summary.txt"
    drc_rc=$?
    set -e
    [ "${drc_rc}" -eq 0 ] || { warn "${name}: post-filter DRC violations present (see drc-summary.txt)"; drc_failed=1; }
  else
    warn "${name}: no DRC JSON report found — cannot verify DRC"; drc_failed=1
  fi

  # Best-effort 3D render (never gates; render_board.sh always exits 0).
  bash "${SCRIPTS}/render_board.sh" "${board}" "${bdir}/out/docs/${name}-3d.png" 2>&1 | tee -a "${bdir}/kibot.log" || true
```

- [ ] **Step 2: Always generate the board BOM (decouple from cross-check)**

In `scripts/entrypoint.sh`, find the BOM block (currently gated on `[ -n "${BOM_CSV}" ]`):
```bash
  if [ -n "${BOM_CSV}" ]; then
    kicad_bom="${bdir}/board-bom.csv"
    python3 "${SCRIPTS}/pcb_bom.py" "${board}" --out "${kicad_bom}" || true
    if [ -f "${kicad_bom}" ]; then
      log "Cross-checking BOM for ${name} against ${BOM_CSV}"
      python3 "${SCRIPTS}/bom_crosscheck.py" \
        --kicad-bom "${kicad_bom}" \
        --altium-bom "${BOM_CSV}" \
        --out "${bdir}/bom-diff.md" || true
      [ -f "${bdir}/bom-diff.md" ] && cat "${bdir}/bom-diff.md" >> "${REPORT}"
    fi
  fi
```
Replace with (always derive the board BOM; cross-check only when an Altium CSV is given):
```bash
  # Always derive the board BOM (artifact in its own right + Phase 4 cross-check input).
  kicad_bom="${bdir}/board-bom.csv"
  python3 "${SCRIPTS}/pcb_bom.py" "${board}" --out "${kicad_bom}" || warn "${name}: board BOM generation failed"
  [ -f "${kicad_bom}" ] && echo "- Board BOM: \`${kicad_bom}\`" >> "${REPORT}"

  # Cross-check vs the Altium golden BOM only when one is supplied (Phase 4).
  if [ -n "${BOM_CSV}" ] && [ -f "${kicad_bom}" ]; then
    log "Cross-checking BOM for ${name} against ${BOM_CSV}"
    python3 "${SCRIPTS}/bom_crosscheck.py" \
      --kicad-bom "${kicad_bom}" \
      --altium-bom "${BOM_CSV}" \
      --out "${bdir}/bom-diff.md" || true
    [ -f "${bdir}/bom-diff.md" ] && cat "${bdir}/bom-diff.md" >> "${REPORT}"
  fi
```

- [ ] **Step 3: Surface the DRC summary in the per-board report**

In `scripts/entrypoint.sh`, inside the per-board report `{ ... } >> "${REPORT}"` block,
after the `Artifacts:` line, add a DRC summary line. Find:
```bash
    echo "- Artifacts: \`${bdir}/out\`"
```
and add immediately after it:
```bash
    if [ -f "${bdir}/drc-summary.txt" ]; then
      echo "- DRC (post-filter): $(head -1 "${bdir}/drc-summary.txt")"
    fi
```

- [ ] **Step 4: shellcheck the entrypoint**

Run: `sg docker -c "docker run --rm -v \"$PWD:/mnt\" -w /mnt koalaman/shellcheck:stable scripts/entrypoint.sh"`
Expected: exit 0. Fix any findings (e.g., the `ls ... | head` is guarded with `2>/dev/null ... || true`; if shellcheck flags SC2012, the guarded form is intentional — add a `# shellcheck disable=SC2012` comment with a one-line justification).

- [ ] **Step 5: Commit**

```bash
git add scripts/entrypoint.sh
git commit -m "Phase 2: entrypoint — always BOM, best-effort render, gate on post-filter DRC"
```

---

## Task 6: Full verification on both fixtures

**Files:** none (verification)

- [ ] **Step 1: Add the Python unit test to `make test`**

In `Makefile`, change the `test` target from:
```makefile
test: shellcheck
	python3 -m py_compile scripts/*.py
	@echo "OK: python compiles"
```
to:
```makefile
test: shellcheck
	python3 -m py_compile scripts/*.py
	python3 tests/test_drc_gate.py
	@echo "OK: python compiles + unit tests pass"
```

- [ ] **Step 2: Static checks pass**

Run: `sg docker -c "docker run --rm -v \"$PWD:/mnt\" -w /mnt koalaman/shellcheck:stable scripts/*.sh" && python3 -m py_compile scripts/*.py && python3 tests/test_drc_gate.py`
Expected: shellcheck exit 0; `OK: drc_gate tests passed`.

- [ ] **Step 3: Run the full gate (report mode)**

Run: `sg docker -c "make image" && sg docker -c "make gate"; echo "EXIT=$?"`
Expected: `EXIT=0`.

- [ ] **Step 4: Verify all Phase 2 artifacts + behaviors**

Run:
```bash
for b in eDP_adapter_dvt1 HiFive1.B01; do
  d=fixtures/kitium-out/build/$b
  echo "== $b =="
  echo "board-bom rows: $(($(wc -l < "$d/board-bom.csv") - 1))"
  echo "render png: $(ls -la "$d"/out/docs/*-3d.png 2>/dev/null | awk '{print $5}' || echo MISSING)"
  echo "drc summary: $(head -1 "$d/drc-summary.txt" 2>/dev/null)"
done
cat fixtures/kitium-out/kitium-report.md
ls -la fixtures/kitium-out/build/eDP_adapter_dvt1/out/fab/gerbers/*.gbr | head -1  # gerbers still present
stat -c '%U' fixtures/kitium-out/kitium-report.md   # owned by you, not root
```
Expected: board-bom ~112 rows each; render PNG present and non-empty (or MISSING with
a logged WARN — acceptable, note it); DRC summary shows a small post-filter count;
report has the Board BOM + DRC lines; gerbers present; files owned by your user.

- [ ] **Step 5: Verify a render failure does NOT fail the gate (gating-fix proof)**

Run (temporarily break render by pointing at a bogus board via a one-off, confirming
exit 0 still):
```bash
sg docker -c "docker run --rm --user \$(id -u):\$(id -g) -e HOME=/tmp -v \"$PWD:/work\" -w /work --entrypoint bash kitium:dev -c 'bash scripts/render_board.sh /work/does-not-exist.kicad_pcb /tmp/x.png; echo RENDER_EXIT=\$?'"
```
Expected: prints the WARN and `RENDER_EXIT=0` (best-effort render never propagates failure).

---

## Task 7: Document Phase 2 findings and update DESIGN.md

**Files:**
- Create: `docs/phase2-findings.md`
- Modify: `DESIGN.md` (§5 validation semantics, §12 feasibility)

- [ ] **Step 1: Write the findings doc**

Create `docs/phase2-findings.md` with the real DRC histogram and decisions:
```markdown
# Kitium Phase 2 — Findings (2026-06-16)

## DRC violation histogram (eDP fixture, post-zone-refill, pre-filter)
1192 total. Errors: clearance 499, track_width 199, drill_out_of_range 178,
solder_mask_bridge 17, hole_clearance 14, starved_thermal 4, unresolved_variable 1,
tracks_crossing 1. Warnings: text_height 118, lib_footprint_issues 112,
silk_over_copper 33, silk_overlap 10, silk_edge_clearance 4, track_dangling 1,
nonmirrored_text_on_back_layer 1.

## Filtering decision
Filtered (import artifacts — board rules/net-classes don't import, DESIGN §11):
clearance, track_width, drill_out_of_range, hole_clearance, solder_mask_bridge,
starved_thermal, unresolved_variable. **NOT filtered:** tracks_crossing (real
geometry) and all warnings. Post-filter error count: <fill from Task 2 Step 3>.

## Render
KiBot render_3d stays disabled; native `kicad-cli pcb render` (best-effort, -full
image) produces the PR thumbnail. Result on fixtures: <fill: works / bare / failed>.

## Gating
`block` mode now keys off the post-filter DRC error count (scripts/drc_gate.py reading
the DRC JSON), NOT KiBot's exit code. Best-effort render/BOM failures never gate.
```
Replace each `<fill ...>` with the real observed value from Task 2/6 — no placeholders left.

- [ ] **Step 2: Update DESIGN.md §12 feasibility note**

In `DESIGN.md` §12, append a note under the table that 3D renders use native
`kicad-cli pcb render` (KiBot's `render_3d` is broken on KiCad 10), and that DRC/pdf
require `xvfb` in the image (KiAuto GUI path), correcting the "clean CLI" classification.

- [ ] **Step 3: Commit**

```bash
git add docs/phase2-findings.md DESIGN.md
git commit -m "Phase 2 complete: record DRC histogram, filter decision, render + gating notes"
```

---

## Done criterion

`make gate` on both fixtures exits 0 in report mode and produces, per board: gerbers,
drill, position, layer PDFs, a filtered DRC report with a small post-filter error
count, a `board-bom.csv` (~112 rows), and a best-effort 3D render PNG. `make test`
(shellcheck + py_compile + `test_drc_gate.py`) passes. A forced render failure does not
fail the gate. Output files are owned by the invoking user. `docs/phase2-findings.md`
has no unfilled placeholders. Phase 3 (PR comment + diff PDF) is then unblocked.
