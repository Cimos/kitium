#!/usr/bin/env bash
# Fidelity check: build a side-by-side page comparing Kitium's converted board against
# a project's PUBLISHED gerbers. DEV TOOL ONLY — it installs gerbv in a throwaway
# container; nothing here ships in the Kitium action image.
#
# Usage:
#   tools/compare/compare.sh <board-repo-root> <pcbdoc-path-rel> <published-gerber-dir-rel>
# Example:
#   tools/compare/compare.sh /tmp/stmblue STM_BLUEPILL.PcbDoc "Project Outputs for STM_BLUEPILL/Gerber"
#
# Output: <root>/compare-out/compare.html (opened in the browser on WSL).
set -euo pipefail

ROOT="$(cd "${1:?board repo root}" && pwd)"
PCBDOC="${2:?.PcbDoc path relative to root}"
REFDIR="${3:?published gerber dir relative to root}"
IMAGE="${IMAGE:-ghcr.io/cimos/kitium:0.1.2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
name="$(basename "${PCBDOC}")"; name="${name%.*}"
OUT="compare-out"
mkdir -p "${ROOT}/${OUT}"

echo "[compare] converting ${PCBDOC} with Kitium (${IMAGE})..."
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e INPUT_BOARDS_GLOB="${PCBDOC}" -e INPUT_DRC=report -e INPUT_OUTPUT_DIR="${OUT}/kitium-out" \
  -v "${ROOT}:/work" -w /work "${IMAGE}" >/dev/null 2>&1 || true

kgerb="${OUT}/kitium-out/build/${name}/out/fab/gerbers"
if [ ! -d "${ROOT}/${kgerb}" ]; then
  echo "[compare] no Kitium gerbers produced — conversion failed (ASCII/Protel Altium, or an unsupported board?)." >&2
  exit 1
fi

echo "[compare] rendering both gerber sets with gerbv..."
docker run --rm -v "${ROOT}:/work" -v "${HERE}:/tools:ro" -w /work \
  -e KGERB="${kgerb}" -e REFDIR="${REFDIR}" -e OUT="${OUT}" \
  --entrypoint bash "${IMAGE}" -c '
    apt-get update >/dev/null 2>&1 && apt-get install -y --no-install-recommends gerbv >/dev/null 2>&1
    render() {  # $1 = gerber dir, $2 = output png
      mapfile -t layers < <(python3 /tools/classify_layers.py "$1")
      if [ "${#layers[@]}" -gt 0 ]; then
        gerbv --export=png --output="$2" --dpi=500 --border=6 "${layers[@]}" 2>/dev/null
      else
        echo "[compare] no recognizable top layers in $1" >&2
      fi
    }
    render "${KGERB}" "${OUT}/kitium-top.png"
    render "${REFDIR}" "${OUT}/ref-top.png"
  '

echo "[compare] building page..."
python3 "${HERE}/build_page.py" --board "${name}" \
  --kitium-png "${ROOT}/${OUT}/kitium-top.png" \
  --ref-png "${ROOT}/${OUT}/ref-top.png" \
  --render-png "${ROOT}/${OUT}/kitium-out/build/${name}/out/docs/${name}-3d.png" \
  --metrics "${ROOT}/${OUT}/kitium-out/build/${name}/metrics.json" \
  --out "${ROOT}/${OUT}/compare.html"

page="${ROOT}/${OUT}/compare.html"
echo "[compare] page: ${page}"
if command -v wslview >/dev/null 2>&1; then
  wslview "${page}" 2>/dev/null || true
elif command -v explorer.exe >/dev/null 2>&1; then
  explorer.exe "$(wslpath -w "${page}" 2>/dev/null)" 2>/dev/null || true
fi
