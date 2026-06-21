# Kitium Phase 0 — De-risk Spike (Design / Spec)

**Date:** 2026-06-16
**Status:** Proposed (awaiting review)
**Scope:** Phase 0 only — turn the code-complete scaffold from *designed* into *proven*.
**Parent design:** [`DESIGN.md`](../../../DESIGN.md) §6 (roadmap), §7 (open questions), §9 (dev loop), §11 (import gotchas).

---

## 1. Goal

Prove, on this WSL2 box, that Kitium's core pipeline actually works against real
Altium boards — before any further building. Phase 0 is **verification**, not
feature work: the scaffold (`entrypoint.sh`, `convert.sh`, the Python guards,
KiBot config, Dockerfile, Makefile) already exists. We are confirming its
documented KiCad 9/10 assumptions hold against a running container.

Success = the four DESIGN.md §6 exit criteria are met and the §7 open questions
are answered from real output.

## 2. The make-or-break risk

The single riskiest assumption is **"KiBot works against KiCad 10."** KiBot
drives KiCad through its `pcbnew` Python API, and the off-the-shelf KiBot
containers (inti-cmnb) stop at **KiCad 8**. We are running KiBot on a KiCad
version its maintainers don't ship. If KiBot's bindings don't load against
KiCad 10, the "assemble, don't rebuild" premise (DESIGN.md §3) partly breaks and
the approach must be reassessed (e.g. pin KiCad 9 — but 9 has no `pcb import`,
so that is a genuine fork in the road, not a config tweak).

Consequence for sequencing: **spike-first**. Prove the two load-bearing facts —
(a) `kicad-cli pcb import` produces a real, loadable board, and (b) KiBot imports
cleanly against KiCad 10 — before relying on the full end-to-end pipeline.

## 3. Constraints / environment (current box state)

- ❌ **Docker not installed** in this WSL2 distro. The entire inner dev loop
  (DESIGN.md §9) runs the KiCad 10 container via `docker run`. Must install
  Docker **Engine** (native WSL2, *not* Docker Desktop).
- ❌ **Local `kicad-cli` is 7.0.11.** `pcb import --format altium` is KiCad
  10-only, so local conversion is impossible without the container regardless.
- ❌ `shellcheck` missing (needed for `make test` / `make shellcheck`).
- ✅ `curl`, `python3` (3.12), `git` present. Fixtures arrive via `curl`, not LFS,
  so `git-lfs` is **not** needed for Phase 0.
- `sudo` on this box requires a password — the installing user runs sudo steps
  interactively (via `! <cmd>` in the session), not the agent.

## 4. Approach (chosen)

**Spike-first, then full gate.** Install runtime → fetch fixtures → build image →
`make spike` (import + preflight assert) → only then `make gate` (full entrypoint).
Rejected alternative: build everything and run `make gate` immediately — faster
"looks done", but tangles import failures with KiBot failures when something breaks.

## 5. Work plan (definition of done)

### 5.1 Setup
1. **Install Docker Engine** (native WSL2). User runs sudo steps via `! <cmd>`;
   agent supplies exact commands and verifies `docker run hello-world`.
2. **Install `shellcheck`** (for `make test`). Skip `act` (Phase 1 middle loop)
   and `git-lfs` (fixtures via curl).
3. **Pin an exact KiCad 10 patch tag** in `Dockerfile` (`ARG KICAD_IMAGE`) and
   `Makefile` (`BASE`), replacing the floating `kicad/kicad:10.0`. Confirm the
   tag exists on Docker Hub; **prefer `10.0.0`, avoid `10.0.1`** (render/STEP
   regression that drops 3D models, DESIGN.md §11).

### 5.2 Prove the core
4. `make fixtures` → eDP adapter (`.PrjPcb` + `.PcbDoc` + 2× `.SchDoc`) and
   HiFive board land in `./fixtures`, OLE-magic verified by the fetcher.
5. `make image` → `kitium:dev` builds and **KiBot pip-installs cleanly** on the
   pinned KiCad 10 image.
6. `make spike` → `kicad-cli pcb import` on the eDP `.PcbDoc` produces a board
   that `pcb_inspect.py --assert` accepts: **>0 footprints, references not
   uniformly `UNK`**.
7. `make gate` → full entrypoint over the fixtures: **KiBot runs** and produces
   a DRC report, gerbers, and 2D/3D renders as artifacts; `make test` (shellcheck
   + py_compile) passes.

### 5.3 Answer §7 open questions from real output
- Exact `pcb import` flag syntax on the pinned image — confirmed ✓/✗.
- **Does KiBot drive KiCad 10's `pcbnew`?** (the §2 gating unknown.)
- Does KiBot produce a `--board-only` BOM, and which component fields survive
  PcbDoc → KiCad import (drives board-BOM usefulness for Phase 4).
- Whether zones import unfilled as documented (validates `refill_zones.py` is needed).

Record answers back into `DESIGN.md` §7 (check the boxes) or a short
`docs/phase0-findings.md`, whichever the implementation plan prefers.

## 6. Exit criteria (gate to Phase 1)

Matches DESIGN.md §6:
1. Converted eDP board loads and passes `pcb_inspect --assert`.
2. DRC + render run via KiBot and produce artifacts.
3. KiBot installs cleanly on the pinned KiCad 10 image.
4. Exact KiCad 10 patch tag pinned in Dockerfile + Makefile.
5. §7 open questions answered and documented.

## 7. Out of scope (deferred)

PR comment / status checks (Phase 3); BOM cross-check tuning (Phase 4); `act` /
CI wiring (Phase 1+ middle/outer loops); schematic ERC + library conversion (GUI
track); real Cubepilot boards (fixtures only this phase); `docker://` GHCR
packaging switch (Phase 5).

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| KiBot can't bind to KiCad 10 `pcbnew` | Caught early by spike-first; if it fails, stop and reassess (KiCad 9 fork has no `pcb import`). |
| Chosen KiCad 10 tag has a regression | Pin `10.0.0`, avoid `10.0.1`; verify renders aren't bare in `make gate`. |
| Docker install needs sudo password | User runs sudo steps interactively via `! <cmd>`. |
| eDP fixture is GPLv3 | Fetched on demand into gitignored `./fixtures`, never committed (fetcher already enforces this). |
| `pcb import` silently empty on Protel/old boards | `convert.sh` OLE-magic check + `pcb_inspect --assert` already guard this. |
