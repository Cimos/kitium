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
| `kicad-cli pcb import --format altium` | `.PcbDoc` | ✅ native CLI (KiCad 9/10) | **Solid** |
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
      - uses: Cimos/kitium@v1
        with:
          project: hardware/MyBoard.PrjPcb   # optional; auto-detected
          bom_csv: hardware/MyBoard_BOM.csv  # Altium-exported golden BOM
          drc: report                         # report | block
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
| **0 — De-risk** | Pull `kicad10_auto_full`; run `kicad-cli pcb import` on a real `.PcbDoc`; load result; run KiBot once | Converted board loads + DRC/render run. **Decision: KiCad 10 vs fall back to 9.** |
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
