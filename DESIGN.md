# Kitium — Design & Roadmap

> **Kitium** = **Ki**(Cad) + (Al)**tium**. A CI/CD gate that converts Altium PCB
> projects to KiCad and validates them on every pull request.
>
> Named for the ancient Cypriot city of **Zeno of Kitium**, founder of Stoicism —
> a fitting patron for a tool whose job is dispassionate, rule-based design review.

---

## 1. Problem & model

We design hardware in **Altium**. We want an *independent*, automated reviewer that
runs on every pull request and tells us, in CI, whether the board is sane — without
adopting KiCad as the source of truth and without buying more Altium seats for CI.

**Chosen model: validation / diff gate.**

- **Altium remains the source of truth.** Engineers keep designing in Altium and
  commit the binary project files.
- **KiCad + KiBot act as an independent reviewer.** On each PR, CI converts the
  Altium board to KiCad headlessly and runs checks + produces review artifacts.
- KiCad files are **ephemeral CI products**, regenerated every run. They are *not*
  committed back and KiCad never becomes canonical.

Explicitly **out of scope**: a one-time migration to KiCad (import fidelity isn't
good enough to make KiCad canonical without heavy human cleanup).

## 2. Feasibility verdict (what this can and can't do)

The make-or-break fact: **headless conversion exists for the PCB, but not the schematic.**

| Capability | Source | Headless? | Verdict |
|---|---|---|---|
| `kicad-cli pcb import --format altium` | `.PcbDoc` | ✅ native CLI (**KiCad 10 only** — not in 9) | **Solid** |
| DRC | PCB | ✅ | **Solid** |
| Gerbers / drill / pick-&-place / fab package | PCB | ✅ | **Solid** |
| 2D plot + 3D render | PCB | ✅ | **Solid** |
| Visual PCB diff (base vs head) | PCB | ✅ (KiBot `diff`) | **Solid** |
| BOM (refdes, value, footprint, qty) | PCB | ✅ | **Partial** — no MPN/supplier fields |
| **Schematic import** (`.SchDoc`) | — | ❌ **No `kicad-cli sch import`** | GUI-only |
| ERC / schematic PDF / hierarchical BOM | Schematic | ⚠️ only via KiAuto + Xvfb (fragile) | **Stretch** |

**Consequences:**

- ✅ A PCB-side reviewer/validation gate is reliable and low-maintenance.
- 🟡 A *procurement* BOM cannot come from the converted PCB (no MPN/manufacturer).
  Those fields live in Altium's schematic / ActiveBOM. **So we keep Altium as the
  BOM authority and cross-check** the converted board's refdes/value/qty against
  Altium's own exported BOM CSV.
- 🔴 Schematic ERC requires driving the KiCad GUI (KiAuto + Xvfb). Treat as
  best-effort, `allow-failure` — never a hard merge gate.

## 3. Build-vs-leverage

The KiCad-*side* CI is a solved, mature problem. We assemble it, we don't rebuild it.

| Component | Source | Decision |
|---|---|---|
| KiCad + KiBot + KiAuto + Xvfb container | `ghcr.io/inti-cmnb/kicadN_auto_full` (KiCad 9/10) | **Base image** |
| Run outputs in CI | `INTI-CMNB/KiBot` GitHub Action / `kibot` CLI | **Reuse** |
| Output config templates | `INTI-CMNB/kicad_ci_test`, `nguyen-v/KDT_Hierarchical_KiBot`, `krsche/kicad-template` | **Crib from** |
| Visual PCB/sch diff between revisions | KiBot `diff` output (→ PDF) | **Reuse** |
| Altium → KiCad **headless conversion front-end** | *nothing exists* — this is us | **Build** |
| BOM cross-check vs Altium CSV | *nothing exists* — this is us | **Build** |
| Glue: locator, multi-board loop, reporting, reusable Action | this is us | **Build** |

**~80% off-the-shelf, ~20% novel.** The older Perl/C# converters
(`thesourcerer8/altium2kicad`, `stevegrn/AtoK`) predate native KiCad import and are
inferior to `kicad-cli pcb import`; not used.

## 4. Architecture

```
┌─ GitHub PR event (push to a consuming repo) ─────────────────────────┐
│  uses: Cimos/kitium@v1   (Docker action; runs in kicadN_auto_full)   │
│                                                                      │
│  1. LOCATE   auto-detect .PrjPcb / .PcbDoc by repo convention        │
│              (override via action inputs); enumerate ALL boards      │  ← novel
│  2. CONVERT  for each board: kicad-cli pcb import --format altium    │  ← novel
│  3. RUN      kibot with kitium config, per board:                    │
│                • DRC (informational by default)                      │
│                • gerbers + drill + pick&place (fab package)          │
│                • 2D plot + 3D render PNG                             │
│                • diff PDF (base vs head)                             │
│                • board-derived BOM CSV                               │
│  4. CHECK    BOM cross-check: board BOM ↔ committed Altium BOM CSV   │  ← novel
│  5. REPORT   PR comment (renders + diff tables)                      │  ← novel
│              + upload artifacts + set status checks                 │
└──────────────────────────────────────────────────────────────────────┘
```

### Consuming-repo interface

```yaml
# .github/workflows/pcb-gate.yml in each hardware repo
name: PCB Gate
on: [pull_request]
jobs:
  kitium:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }   # diff needs history
      - uses: Cimos/kitium@v0   # pre-1.0
        with:
          project: hardware/MyBoard.PrjPcb   # optional; auto-detected
          bom_csv: hardware/MyBoard_BOM.csv  # Altium-exported golden BOM
          drc: report                         # report | block
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

## 5. Validation semantics

KiBot's `diff` is a *review artifact* (a PDF), **not** an auto pass/fail — gating
logic is ours. The gate is a **hybrid**, not pure rule-checks (raw DRC on freshly
converted boards is noisy and would cry wolf):

| Signal | Behaviour |
|---|---|
| `kicad-cli pcb import` exit code | **Hard fail** |
| Structural metrics (component / net / pad / layer count, board area) | Diff **commit-to-commit**; flag in PR comment |
| BOM refdes/qty parity vs Altium CSV | **Soft fail** / flag (tune later) |
| 2D plot + 3D render + diff PDF | Posted to PR as **reviewer aid** |
| DRC | **Informational** first; promote to hard gate once baseline is clean |
| ERC / schematic PDF (KiAuto+Xvfb) | Stretch, `allow-failure` |

No "golden" Altium gerbers are required to start; commit-to-commit diffing gives
immediate value. Golden-baseline comparison is a later add-on.

## 6. Roadmap

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0 — De-risk** | Build on `kicad/kicad:10.0` + `pip install kibot`; run `kicad-cli pcb import` on a real `.PcbDoc`; load result; run KiBot once | Converted board loads + DRC/render run; KiBot installs cleanly. **Pick exact KiCad 10 patch tag (avoid 10.0.1).** |
| **1 — Conversion shim + container** | Entrypoint locates project, loops multi-board, converts each, stages `.kicad_pcb` | Multi-board sample fully converted in CI |
| **2 — Core KiBot outputs** | Kitium KiBot config: DRC (info) + gerbers + renders + `diff` PDF + board BOM | Artifacts produced for every board |
| **3 — PR experience** | PR comment (renders + tables), artifact upload, status checks (conversion = hard, DRC = soft) | Real PR shows comment + checks |
| **4 — BOM cross-check** | Parse board BOM, diff vs Altium CSV (refdes/qty parity) | Mismatch table in PR comment |
| **5 — Packaging** | Versioned reusable Action; onboard a 2nd repo | Second repo green with a few lines of YAML |
| **6 — Stretch (optional)** | KiAuto+Xvfb `.SchDoc` import → ERC + sch PDF, `allow-failure` | Best-effort; clearly non-blocking |

Gate thresholds (DRC strictness etc.) are tuned **after Phase 2/3**, from real output.

## 7. Open questions / assumptions to confirm in Phase 0

- [ ] Exact `kicad-cli pcb import` flag syntax & altium support on the pinned image.
- [ ] Does the current KiBot release fully support KiCad 10's `pcbnew` API? (else pin KiCad 9.)
- [ ] The repos' **"consistent convention"**: where `.PrjPcb`/`.PcbDoc` live + naming pattern (drives auto-detect).
- [ ] Altium BOM CSV column names (for the cross-check column mapping).
- [ ] Which component fields survive PcbDoc → KiCad footprint import (affects board-BOM usefulness).

## 8. Known risks

- **Schematic path fragility** — KiAuto+Xvfb dialog-blocking; keep non-blocking.
- **Import fidelity drift** — KiCad importer changes between versions can shift output;
  pin the KiCad version in the image and bump deliberately.
- **DRC noise** on converted boards — start informational, harden gradually.
- **Multi-board projects** — outputs must be keyed per board; never assume one PcbDoc.

---

# Research-validated path (added 2026-06-15)

A 5-track research sweep (dev loop, test data, git binaries, packaging, import
gotchas) refined the plan below. Sources are linked inline.

## 9. Dev/test loop — three concentric loops

The deliverable *is* a Docker action, but iterating purely in CI is the wrong inner
loop (1–5 min/round-trip). Use three loops, fastest first:

1. **Inner (where ~90% of work happens):** run the KiCad container directly against a
   sample board — `docker run --rm -v $PWD:/work <img> kicad-cli pcb import --format altium /work/board.PcbDoc`.
   Native **Docker Engine in WSL2** (not Docker Desktop) — ~90% native perf, no licensing.
   Keep everything in WSL ext4 (`~/git/kitium`, already correct) — **never** `/mnt/c`
   (cross-OS small-file I/O is brutal).
2. **Middle:** `nektos/act` to validate the workflow YAML / action wiring (inputs,
   outputs, `${{ }}`, PR-comment step). Reuses the local daemon. Plumbing smoke-test
   only — *passing in act ≠ passing in CI*.
3. **Outer (fidelity gate):** real GitHub Actions on a scratch branch.

## 10. Packaging — prebuilt GHCR image, referenced via `docker://`

**Decision:** `action.yml` must reference a **prebuilt image** (`image: docker://ghcr.io/cimos/kitium:<tag>`),
**not** `image: Dockerfile`. GitHub runners are ephemeral with no layer cache, so a
Dockerfile-type action **rebuilds the ~1 GB image on every run**. Prebuilt = one ~20 s
pull, and local `docker run` + CI use the *identical* artifact.

- A **separate release workflow** builds + pushes to GHCR on a version-tag push
  (`docker/build-push-action` + `cache-to/from: type=gha`).
- Versioning: immutable `vX.Y.Z` on git ref **and** image; moving major tag (pre-1.0:
  `v0` git ref / `:0` image — published via `type=raw,value=0` because metadata-action
  suppresses `{{major}}` for 0.x). Keep git tag ↔ image tag in lockstep (classic silent bug).
- **Chicken-and-egg:** the image must exist in GHCR *before* the first `uses:` works —
  push the image in the release job (or a manual `workflow_dispatch`) first.
- **Base image (corrected):** `kicad-cli pcb import` is **KiCad 10-only** (NOT in the
  9.0 CLI), and the inti-cmnb KiBot images stop at KiCad 8 — so neither provides import.
  We build on the **official `kicad/kicad:10.0`** image and add KiBot via `pip install
  --break-system-packages kibot`. Pin an exact patch tag and **avoid 10.0.1** (render/STEP
  regression that drops 3D models, §11). KiAuto/Xvfb (for the later GUI track) get added then.

> ⚠️ The current scaffold's `action.yml` still uses `image: "Dockerfile"` — switch to
> `docker://` once the first image is published to GHCR.

## 11. Critical import gotchas (correctness-shaping)

These reshape *what we build*, not just config knobs:

- **No `kicad-cli pcb export bom` — in KiCad 9 *or* 10** ([gitlab #16302], open). A
  board-only import yields no CLI BOM. → Board-derived BOM must come from **KiBot
  parsing the `.kicad_pcb`** (or `pcb export ipc2581` BOM columns). Altium CSV stays the
  BOM authority; we cross-check refdes/qty. Confirm KiBot `--board-only` BOM in Phase 0.
- **DRC is noisy by design.** Altium design rules + **net-class membership don't import**
  ([#15584]); **polygon cutouts import as over-restrictive keepouts** ([#15587]); **zones
  import UNFILLED**. → **Re-fill zones** before DRC/gerber/render; **whitelist** known
  false positives; gate with `drc --exit-code-violations --severity-error` + filters,
  **never on raw counts**.
- **Silent failure on old/ASCII (Protel) PcbDoc** ([#18467]) — imports with *no error*.
  → **Pre-flight: assert board has >0 footprints/tracks; fail loud; surface stderr.**
- **Refdes can regress to `UNK`** ([#18502], version-dependent) — breaks BOM cross-check.
  → **Pre-flight: assert references aren't uniformly `UNK`.**
- **3D placement read but not applied** + a **`pcb render`/`export step` regression in
  9.0.9 & 10.0.1** that drops component models → renders may look bare. → Pin a known-good
  patch (9.0.7 / 10.0.0), pass `--subst-models`, set 3D-model search-path env. **Renders
  are best-effort, never a gate.**
- **Layer mapping is lossy & normally interactive** — headless can't drive the mapping
  dialog. → Verify mechanical/keepout/courtyard layers land where gerbers expect.
- **Library conversion is GUI-only.** `kicad-cli` can *open* `.PcbLib/.SchLib` (read-only,
  KiCad 8+) but **cannot migrate** them to `.kicad_mod/.kicad_sym` — that's a GUI action.
- **Schematic import is GUI-only** (PrjPcb/flat-sch import added 9.0.3, still GUI-oriented).

[gitlab #16302]: https://gitlab.com/kicad/code/kicad/-/work_items/16302
[#15584]: https://gitlab.com/kicad/code/kicad/-/issues/15584
[#15587]: https://gitlab.com/kicad/code/kicad/-/issues/15587
[#18467]: https://gitlab.com/kicad/code/kicad/-/issues/18467
[#18502]: https://gitlab.com/kicad/code/kicad/-/issues/18502

## 12. Revised scope & feasibility (the GUI-only reality)

Of the four things wanted for v1, **two are clean CLI and two require fragile GUI
automation** (KiAuto + Xvfb). They split cleanly:

| Feature | Path | Bucket |
|---|---|---|
| PCB convert + DRC + gerbers + fab | `kicad-cli` + KiBot | ✅ **v1 core (clean CLI)** |
| 3D renders | `kicad-cli`/KiBot | 🟡 **v1, best-effort** (bare models; never a gate) |
| BOM cross-check | KiBot board-BOM ↔ Altium CSV | ✅ **v1 core** |
| **Schematic ERC / sch PDF** | KiAuto + Xvfb (GUI drive) | 🔴 **GUI-automation track** (later) |
| **Altium library conversion** | KiAuto + Xvfb (GUI "Migrate") | 🔴 **GUI-automation track** (later) |

**Recommendation:** ship the clean-CLI core (PCB gate + best-effort renders + BOM
cross-check) as v1; group schematic ERC **and** library conversion into a single later
**GUI-automation track**, since they share the same fragile KiAuto+Xvfb machinery.

## 13. Test corpus — Phase 0 is no longer blocked on your board

KiCad's own Altium-importer **regression fixtures** are the ideal dev corpus (the exact
files KiCad validates its importer against), fetched on demand from the GitHub mirror:

- **Primary (end-to-end):** `eDP_adapter_dvt1_source/` — real `.PrjPcb` + `.PcbDoc` +
  two `.SchDoc` (Kosagi Novena eDP adapter). The only fixture with a full project tying a
  board to multiple sheets — mirrors Kitium's whole pipeline.
- **Second board:** `HiFive/HiFive1.B01.PcbDoc` (SiFive RISC-V dev board).
- **Stress:** `issue24456/Fastino_Ground_Isolator.PcbDoc` (8.3 MB).
- **Libraries (with golden outputs):** `pcblib/Tracks.v5/v6.PcbLib`, Espressif `.PcbLib`.

> **Licensing:** as committed into KiCad these are **GPLv3** — so **do not vendor** them.
> Download at dev/CI time from `raw.githubusercontent.com/KiCad/kicad-source-mirror/master/qa/data/pcbnew/plugins/altium/…`
> (verify OLE magic `D0CF11E0A1B11AE1`). For anything we must commit, use the permissive
> **venky-vn/STM32_BLUEPILL** (MPL-2.0). `scripts/fetch_fixtures.sh` fetches the corpus.

## 14. Git binary handling (storage varies per repo)

The action must be **LFS-agnostic and fail loud on pointer files**:

- An unresolved LFS pointer is a ~130-byte text file, **not** a board — feeding it to
  `kicad-cli` is a silent failure. The pre-flight OLE-magic check (§11) catches this too.
- Detect LFS via `.gitattributes` / `git lfs ls-files`; only `git lfs pull` when the repo
  actually tracks design files (blanket `lfs: true` errors on non-LFS repos).
- `git-lfs` is on GitHub runners but **not** inside containers → materialize LFS on the
  runner at checkout, not inside Kitium's container.
- Every `lfs:true` checkout burns LFS **bandwidth quota** (10 GiB/mo Free/Pro) → consumers
  should cache LFS objects ([nschloe/action-cached-lfs-checkout]).
- **Project policy** (recommended to repos): track `*.PcbDoc *.SchDoc *.PcbLib *.SchLib
  *.step` in LFS + the canonical [Altium `.gitignore`].

[nschloe/action-cached-lfs-checkout]: https://github.com/nschloe/action-cached-lfs-checkout
[Altium `.gitignore`]: https://github.com/github/gitignore/blob/main/community/AltiumDesigner.gitignore
