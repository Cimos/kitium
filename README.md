# Kitium

**CI/CD gate that converts Altium PCB projects to KiCad and validates them — DRC,
gerbers, renders, and a BOM cross-check — on every pull request.**

`Ki`(Cad) + (Al)`tium`. Lives in the KiCad-automation family next to
[`kibot`](https://github.com/INTI-CMNB/KiBot) and `kiauto`.

> 🏛️ Named for the ancient Cypriot city of **Zeno of Kitium**, founder of Stoicism —
> a fitting patron for a tool whose job is dispassionate, rule-based design review.

---

## Status

🚧 **Early scaffold (pre-Phase 0).** The design is settled (see
[`DESIGN.md`](./DESIGN.md)); the runtime is not yet verified end-to-end. The
conversion command and KiBot config in this repo are written against the documented
KiCad 9/10 behaviour and will be confirmed against a real Altium project in Phase 0.

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

- ✅ PCB conversion, DRC, gerbers, renders, visual diff — solid (native, headless).
- 🟡 BOM — validated by **cross-check against your Altium BOM export** (KiCad can't
  recover MPN/supplier fields from the PCB alone).
- 🔴 Schematic ERC — only via fragile GUI automation; a non-blocking stretch goal.

See [`DESIGN.md`](./DESIGN.md) §2 for the full feasibility breakdown.

## Quickstart (planned interface)

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
      - uses: Cimos/kitium@v0   # pre-1.0; pin a concrete @v0.x.y for reproducibility
        with:
          project: hardware/MyBoard.PrjPcb   # optional; auto-detected
          bom_csv: hardware/MyBoard_BOM.csv  # Altium-exported golden BOM
          drc: report                         # report | block
          github_token: ${{ secrets.GITHUB_TOKEN }}  # for the sticky PR comment
```

See [`examples/consumer-workflow.yml`](./examples/consumer-workflow.yml).

## Repo layout

```
action.yml                 # reusable Docker-based GitHub Action
Dockerfile                 # FROM inti-cmnb kicad image + kitium scripts
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
