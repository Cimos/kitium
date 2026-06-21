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
