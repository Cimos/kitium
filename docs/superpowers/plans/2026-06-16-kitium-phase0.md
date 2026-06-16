# Kitium Phase 0 — De-risk Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Kitium's core pipeline (Altium→KiCad import + KiBot DRC/render) works against real fixtures on this WSL2 box, and answer the DESIGN.md §7 open questions from real output.

**Architecture:** Spike-first verification. Install Docker Engine (native WSL2) → pin an exact KiCad 10 image tag → build the `kitium:dev` container → prove `kicad-cli pcb import` + `pcb_inspect --assert` on the eDP fixture → run the full `entrypoint.sh` gate → record findings. No new features; the scaffold already exists.

**Tech Stack:** Docker Engine (WSL2/systemd), KiCad 10 (`kicad/kicad:10.0.0`), KiBot (pip), Bash, Python 3 stdlib, GNU Make, shellcheck.

**Spec:** [`docs/superpowers/specs/2026-06-16-kitium-phase0-design.md`](../specs/2026-06-16-kitium-phase0-design.md)

> **Convention note:** "Verify it fails / passes" here means running the existing
> guards (`pcb_inspect --assert`, `shellcheck`, `py_compile`) and `make` targets as
> the test harness — Phase 0 is verification of existing code, not new feature TDD.
> Steps marked **[USER ACTION]** require sudo and must be run by the user via
> `! <cmd>` in the session; the agent supplies the exact command and reads the output.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `Dockerfile` | Modify (`ARG KICAD_IMAGE`) | Pin exact KiCad 10 base tag |
| `Makefile` | Modify (`BASE`) | Pin same tag for the local dev loop |
| `docs/phase0-findings.md` | Create | Record §7 answers + the pinned tag rationale |
| `DESIGN.md` | Modify (§7 checkboxes) | Mark open questions resolved |

No source-logic files change unless the spike surfaces a bug (see Task 7 contingency).

---

## Task 1: Install Docker Engine (native WSL2)

**Files:** none (environment setup)

- [ ] **Step 1: [USER ACTION] Add Docker's apt repository**

Run (user, via `!`):
```bash
sudo install -m 0755 -d /etc/apt/keyrings && \
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
sudo chmod a+r /etc/apt/keyrings/docker.gpg && \
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```
Expected: `docker.list` written, no errors.

- [ ] **Step 2: [USER ACTION] Install Docker Engine packages**

Run (user, via `!`):
```bash
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
Expected: packages install; `docker --version` prints `Docker version 2x.x`.

- [ ] **Step 3: [USER ACTION] Enable + start the daemon and add user to docker group**

Run (user, via `!`):
```bash
sudo systemctl enable --now docker && sudo usermod -aG docker "$USER"
```
Expected: no error. **The group change requires a new shell** — open a fresh terminal (or `newgrp docker`) before Step 4.

- [ ] **Step 4: Verify Docker works rootless-for-user**

Run: `docker run --rm hello-world`
Expected: "Hello from Docker!" message. If `permission denied` on the socket, the docker-group shell hasn't been refreshed — start a new shell and retry.

- [ ] **Step 5: Commit**

No repo changes in this task — nothing to commit.

---

## Task 2: Install shellcheck (for `make test`)

**Files:** none (environment setup)

- [ ] **Step 1: [USER ACTION] Install shellcheck**

Run (user, via `!`): `sudo apt-get install -y shellcheck`
Expected: installs.

- [ ] **Step 2: Verify**

Run: `shellcheck --version`
Expected: prints version `0.9.x` or similar.

---

## Task 3: Pin the exact KiCad 10 base tag

**Files:**
- Modify: `Dockerfile:10` (`ARG KICAD_IMAGE=kicad/kicad:10.0`)
- Modify: `Makefile:11` (`BASE  ?= kicad/kicad:10.0`)

Available tags confirmed on Docker Hub: `10.0.0`, `10.0.1`, `10.0.2`. We pin
**`10.0.0`** — the DESIGN.md §11 documented known-good — and avoid `10.0.1` (render/STEP
regression). `10.0.2` is a later bump candidate but unverified here.

- [ ] **Step 1: Pin the Dockerfile ARG**

In `Dockerfile`, change line 10 from:
```dockerfile
ARG KICAD_IMAGE=kicad/kicad:10.0
```
to:
```dockerfile
ARG KICAD_IMAGE=kicad/kicad:10.0.0
```

- [ ] **Step 2: Pin the Makefile BASE**

In `Makefile`, change line 11 from:
```makefile
BASE  ?= kicad/kicad:10.0   # pcb import is KiCad 10-only; official image + pip KiBot
```
to:
```makefile
BASE  ?= kicad/kicad:10.0.0   # pinned: 10.0.0 known-good; AVOID 10.0.1 (render regression)
```

- [ ] **Step 3: Verify the tags match**

Run: `grep -n '10.0.0' Dockerfile Makefile`
Expected: one hit in each file.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile Makefile
git commit -m "Pin KiCad base image to 10.0.0 (avoid 10.0.1 render regression)"
```

---

## Task 4: Fetch the test fixtures

**Files:** none (writes gitignored `./fixtures`)

- [ ] **Step 1: Run the fetcher**

Run: `make fixtures`
Expected: `[kitium] fixtures: 5 ok, 0 failed -> fixtures/`, with each `.PcbDoc`/`.SchDoc`
reported as "OLE binary OK".

- [ ] **Step 2: Verify the eDP board is a real OLE file**

Run: `od -An -tx1 -N8 fixtures/eDP_adapter_dvt1_source/eDP_adapter_dvt1.PcbDoc | tr -d ' \n'`
Expected: `d0cf11e0a1b11ae1`.

- [ ] **Step 3: Confirm fixtures stay untracked**

Run: `git status --porcelain fixtures/`
Expected: **no output** (fixtures are gitignored — never committed, they are GPLv3).

---

## Task 5: Build the Kitium image (proves KiBot installs on KiCad 10)

**Files:** none (builds `kitium:dev`)

- [ ] **Step 1: Build the image**

Run: `make image`
Expected: build succeeds; the `pip3 install ... kibot` layer completes without error.
This is the first half of the §2 make-or-break check (KiBot **installs** on KiCad 10).

- [ ] **Step 2: Verify KiBot can import KiCad 10's pcbnew (the gating check)**

Run:
```bash
docker run --rm --entrypoint bash kitium:dev -c 'kibot --version && python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"'
```
Expected: KiBot prints its version, AND `pcbnew.GetBuildVersion()` prints a `10.0.0`
string with no `ImportError`/segfault.
**If this fails:** STOP. This is the DESIGN.md §2 fork — KiBot cannot drive KiCad 10.
Record the failure in `docs/phase0-findings.md` and escalate before continuing (the
KiCad 9 fallback has no `pcb import`, so this needs a design decision, not a code fix).

---

## Task 6: Spike — convert the eDP board and assert it loaded

**Files:** none (writes gitignored `fixtures/out`)

- [ ] **Step 1: Run the spike**

Run: `make spike`
Expected: `kicad-cli pcb import` writes `fixtures/out/spike.kicad_pcb`, then
`pcb_inspect.py --assert` exits 0.

- [ ] **Step 2: Verify the import report has no fatal diagnostics**

Run: `python3 -m json.tool fixtures/out/spike-import.json`
Expected: valid JSON; note any warnings for the findings doc.

- [ ] **Step 3: Verify the board is non-empty and refs aren't all UNK**

Run: `python3 scripts/pcb_inspect.py fixtures/out/spike.kicad_pcb --metrics-out fixtures/out/spike-metrics.json && python3 -m json.tool fixtures/out/spike-metrics.json`
Expected: footprint count > 0; references are real (not uniformly `UNK`). This is the
§11 silent-import + UNK-refdes guard passing against a real board.

---

## Task 7: Run the full gate over the fixtures

**Files:** none (writes gitignored `fixtures/kitium-out`); contingency edits noted below.

- [ ] **Step 1: Static checks pass**

Run: `make test`
Expected: `shellcheck scripts/*.sh` clean, `py_compile scripts/*.py` clean, prints `OK: python compiles`.

- [ ] **Step 2: Run the end-to-end gate**

Run: `make gate`
Expected: entrypoint converts every fixture board, refills zones, runs KiBot, and writes
`fixtures/kitium-out/kitium-report.md`. Exit code 0 (DRC is `report` mode, non-blocking).

- [ ] **Step 3: Verify KiBot produced the core artifacts**

Run: `find fixtures/kitium-out -type f \( -name '*.gbr' -o -name '*.pdf' -o -name '*.png' -o -name 'drc*' \) | sort`
Expected: gerbers, a DRC report, and at least one render/plot per board.

- [ ] **Step 4: Check renders aren't bare (best-effort)**

Inspect any 3D render PNG under `fixtures/kitium-out`. Expected: components visible.
**Contingency:** if renders are bare due to missing 3D model libraries, re-pin to the
`-full` image variant (`kicad/kicad:10.0.0-full`) in Dockerfile + Makefile, rebuild,
re-run `make gate`. Renders are best-effort and never a gate — record the outcome, don't block.

- [ ] **Step 5: Read the generated report**

Run: `cat fixtures/kitium-out/kitium-report.md`
Expected: a per-board section with a metrics `<details>` block. Sanity-check the numbers.

- [ ] **Step 6: Commit (only if Step 4 contingency changed the tag)**

```bash
git add Dockerfile Makefile
git commit -m "Switch to kicad/kicad:10.0.0-full for component 3D renders"
```
Skip this commit if no tag change was needed.

---

## Task 8: Record findings and close the §7 open questions

**Files:**
- Create: `docs/phase0-findings.md`
- Modify: `DESIGN.md` §7 (check resolved boxes)

- [ ] **Step 1: Write the findings doc**

Create `docs/phase0-findings.md` capturing, from the real output of Tasks 5–7:
```markdown
# Kitium Phase 0 — Findings (2026-06-16)

**Pinned base image:** `kicad/kicad:10.0.0` (avoided 10.0.1 render regression). [+`-full` if Task 7 Step 4 required it]

## §7 open questions — resolved
- **`pcb import` flag syntax on the pinned image:** <confirmed flags / any deviation>
- **KiBot drives KiCad 10 `pcbnew`:** <YES + versions, or NO + the failure>
- **Board-only BOM / surviving component fields:** <which fields survived PcbDoc→KiCad>
- **Zones import unfilled:** <confirmed / not — validates refill_zones.py>

## Artifacts observed
- Gerbers: <yes/no>  DRC report: <yes/no>  2D plot: <yes/no>  3D render: <bare/ok>

## Surprises / follow-ups for Phase 1
- <anything that changes the Phase 1 plan>
```
Fill every `<...>` with the actual observed result — no placeholders left in the committed file.

- [ ] **Step 2: Check the resolved boxes in DESIGN.md §7**

For each §7 question answered, change `- [ ]` to `- [x]` and append a one-line result
referencing `docs/phase0-findings.md`.

- [ ] **Step 3: Verify exit criteria are all met**

Confirm against the spec §6:
1. eDP board loads + passes `--assert` (Task 6) ✓
2. DRC + render run, artifacts produced (Task 7) ✓
3. KiBot installs cleanly on KiCad 10 (Task 5) ✓
4. Exact KiCad 10 tag pinned (Task 3) ✓
5. §7 questions documented (this task) ✓

- [ ] **Step 4: Commit**

```bash
git add docs/phase0-findings.md DESIGN.md
git commit -m "Phase 0 complete: record findings, resolve DESIGN §7 open questions"
```

---

## Done criterion

All Task 8 Step 3 exit criteria checked, `docs/phase0-findings.md` committed with no
unfilled placeholders, and the `make gate` run produces artifacts for every fixture board.
Phase 1 (conversion shim + container hardening) is then unblocked.
