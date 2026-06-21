# Altium-CI productization — status & roadmap

Where the effort to turn Kitium into a full **Altium CI/CD pipeline** stands, and
what's next. Complements `DESIGN.md` (which holds the original Phase 0–6 design);
this file tracks the higher-level productization milestones and the live status.

_Last updated: 2026-06-21._

## Goal

Give Altium projects the same CI a KiCad+KiBot pipeline gives: on every PR —
fab datapacks, ERC/DRC, renders, a visual PCB diff, BOM checks, and a design-review
comment; on a tag — a published release.

**Architecture (proven):** Altium stays canonical. On each PR, convert each board
to KiCad **headlessly** with `kicad-cli pcb import` (KiCad 10, no Altium license,
no GUI), then run the KiBot pipeline on the converted board. KiCad is an ephemeral,
never-committed intermediate. Build on Kitium rather than starting fresh.

## Where we are

- **`v0.1.0`** — the PCB gate works end-to-end (Phase 0 + 2): headless conversion,
  zone refill, filtered DRC gate, gerbers/drill/position/PDFs, 3D render, board BOM.
- **Visual diff** — implemented (`scripts/pcb_diff.sh` + the `pcb_diff` output in
  `kibot/kitium.kibot.yaml` + BASE_REF wiring in `entrypoint.sh`): fetches the PR
  base revision's `.PcbDoc` from git, converts + refills it, runs KiBot's red/green
  file-vs-file diff. Never gates.

### ✅ M0 — Truth-up & hardening (COMPLETE)

Merged to `main`:

- **T1 Truth-up** — README / DESIGN.md / script headers now reflect the real
  `v0.1.0` state (not "pre-Phase 0 scaffold").
- **T2 End-to-end CI gate** — `selftest.yml` gained an `end-to-end` job that builds
  the KiCad-10 container, fetches KiCad's Altium fixture on demand (`fetch_fixtures.sh`,
  GPLv3 — never vendored), runs the real gate, and asserts a populated datapack.
  **Verified live** converting `eDP_adapter_dvt1` + `HiFive1.B01`.
- **T3 Fork-safe PR-comment split** — added an action `mode: comment`; the consumer
  template is now two workflows: analysis on `pull_request` (`contents: read`, uploads
  the report + PR number) and a `workflow_run` companion (`pull-requests: write`) that
  posts the comment. The write token never touches design-file processing.
  `post_comment.py` takes a validated-numeric `KITIUM_PR_NUMBER` override.
- **T4 GHCR image** — chicken-and-egg already documented; removed the stale
  contradicting warning.

## Roadmap (next)

### M1 — PR experience (NEXT — scoped)

Visual diff is already implemented; the remaining "PR experience" work is:

- **Diff images in the comment** — the report currently links the diff **PDF**
  (not viewable inline). Render the KiBot diff to **PNG** and embed/link it in the
  sticky comment so reviewers see the change. _(Highest-value gap.)_
- **Richer comment tables** — DRC summary + BOM-delta as Markdown tables, collapsible
  per-board.

(Deferred from M1 unless asked: explicit commit status check; e2e coverage of the
diff path — the current e2e runs a single ref so the diff is skipped.)

### M2 — BOM cross-check productionization _(blocked on a real fixture)_

Confirm Altium BOM CSV column mapping against a real ActiveBOM/BomDoc export; settle
the `.PcbDoc`/`.PrjPcb` repo-layout convention; harden refdes/qty parity.

### M3 — Datapack & release parity

2D image set + rotating-video frames; align outputs/naming with `kibot-config`;
release-on-tag (Altium project → zipped datapacks → GitHub Release, SHA-pinned).

### M4 — AI design review

Run `kicad-happy` on the converted board (fork-safe two-workflow split; SHA-pinned;
no LLM egress unless opted in), matching the Mad_RP2040 gate.

### M5 — Connectivity & ERC spike _(the hard blocker)_

- **Nets don't survive import** (KiCad gitlab #15584) → no ERC, weaker semantic
  checks; caps the pure-conversion approach at PCB-geometry scope.
- **No headless schematic import** → ERC needs fragile Xvfb/GUI automation or the
  Altium 365 API.
- Spike both, then a decision gate: commit to a connectivity/ERC strategy or formally
  scope it out of v1.

### M6 — Packaging, onboarding & GA

Onboard a second real Altium repo; docs, consumer templates, Marketplace listing,
pinning policy; full security review; tag `v1.0.0`.

## Open decisions (steer the plan)

- **v1 scope:** PCB-only parity (recommended — builds on what works) vs. include
  schematic + ERC (needs Altium 365 or Xvfb).
- **Altium 365 API access?** — unlocks the nets/schematic path (M5).
- **Real Altium fixture** — a project + BOM export is needed to unblock M2.

## Conventions

- Commits authored by the maintainer only — **no AI/Claude co-author trailers**.
- Merge via squash PR to `main`. Third-party actions **SHA-pinned** (audit before
  adopting). Fork-safe pattern everywhere: `pull_request` (read-only) +
  `workflow_run` (privileged), never `pull_request_target`.
- Pin KiCad to an exact patch (KiCad 10; avoid 10.0.1 — render/STEP regression).
