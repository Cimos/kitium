# Kitium

**CI/CD gate that converts Altium PCB projects to KiCad and validates them — DRC,
gerbers, renders, and a BOM cross-check — on every pull request.**

`Ki`(Cad) + (Al)`tium`. Lives in the KiCad-automation family next to
[`kibot`](https://github.com/INTI-CMNB/KiBot) and `kiauto`.

> 🏛️ Named for the ancient Cypriot city of **Zeno of Kitium**, founder of Stoicism —
> a fitting patron for a tool whose job is dispassionate, rule-based design review.

---

## Status

**`v0.1.0` — the PCB gate works end-to-end.** Phase 0 (de-risk) and Phase 2 (core
outputs) are complete and verified on real Altium fixtures (KiCad's `eDP_adapter_dvt1`
and `HiFive1.B01`): headless conversion, zone refill, a filtered DRC gate, gerbers /
drill / position / layer-PDFs, a 3D render, and a board-derived BOM all run in the
KiCad-10 container.

- ✅ **Working today:** PCB conversion · DRC gate (`report`/`block`) · fab outputs ·
  3D render · board BOM · BOM cross-check (when an Altium BOM CSV is supplied).
- 🟡 **Wired but not yet hardened:** the sticky PR comment (Phase 3) and the
  base-vs-head **visual diff** (base-ref wiring pending).
- 🔴 **Not started:** schematic **ERC** — no headless `.SchDoc` import; a
  non-blocking stretch goal (Phase 6).

See [`DESIGN.md`](./DESIGN.md) §6 for the roadmap.

## What it does

Altium stays your **source of truth**. On each PR, Kitium runs in CI and:

1. **Locates** the Altium project (`.PrjPcb` / `.PcbDoc`) — every board, including
   multi-board projects.
2. **Converts** each board to KiCad headlessly with `kicad-cli pcb import --format altium`
   (no Altium license, no GUI).
3. **Validates** with KiBot — DRC, gerbers, 2D/3D renders, and a base-vs-head visual diff.
4. **Cross-checks** the board's BOM against your Altium-exported BOM CSV.
5. **Reports** back to the PR — comment with renders + diff tables, uploaded artifacts,
   and status checks.

It does **not** make KiCad your source of truth and does **not** commit KiCad files back.

### What's reliable vs not

- ✅ PCB conversion, DRC, gerbers, renders — solid (native, headless).
- 🟡 Visual diff — config is in place; base-ref wiring is pending (Phase 3).
- 🟡 BOM — validated by **cross-check against your Altium BOM export** (KiCad can't
  recover MPN/supplier fields from the PCB alone).
- 🔴 Schematic ERC — only via fragile GUI automation; a non-blocking stretch goal.

See [`DESIGN.md`](./DESIGN.md) §2 for the full feasibility breakdown.

## Quickstart

Add to a hardware repo:

```yaml
# .github/workflows/pcb-gate.yml
name: PCB Gate
on: [pull_request]
jobs:
  kitium:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: Cimos/kitium@v0.1.0   # pre-1.0; pin a concrete @v0.x.y for reproducibility
        with:
          project: hardware/MyBoard.PrjPcb   # optional; auto-detected
          bom_csv: hardware/MyBoard_BOM.csv  # Altium-exported golden BOM
          drc: report                         # report | block
          github_token: ${{ secrets.GITHUB_TOKEN }}  # for the sticky PR comment
```

See [`examples/consumer-workflow.yml`](./examples/consumer-workflow.yml).

## Repo layout

```
action.yml                 # Docker-based GitHub Action (runs a prebuilt GHCR image)
Dockerfile                 # FROM kicad/kicad:10 + KiBot + kitium scripts
scripts/
  entrypoint.sh            # orchestrates locate → convert → kibot → report
  convert.sh               # kicad-cli pcb import, multi-board loop
  bom_crosscheck.py        # board BOM ↔ Altium BOM CSV
kibot/
  kitium.kibot.yaml        # KiBot config: drc, gerbers, render, diff, bom
examples/
  consumer-workflow.yml    # drop-in workflow for a consuming repo
DESIGN.md                  # design & roadmap (start here)
```

## Acknowledgements

Built on the shoulders of [KiCad](https://www.kicad.org/),
[KiBot](https://github.com/INTI-CMNB/KiBot), and KiAuto by INTI-CMNB.

## License

[MIT](./LICENSE)
