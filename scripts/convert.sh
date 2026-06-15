#!/usr/bin/env bash
# Locate Altium .PcbDoc files and convert each to KiCad with kicad-cli.
# Prints the resulting .kicad_pcb paths (one per line) on stdout.
#
# Inputs via env: PROJECT, BOARDS_GLOB, BUILD_DIR
#
# STATUS: scaffold. Verify exact `kicad-cli pcb import` flags against the pinned
# image in Phase 0 (documented: --format altium --output <out> <input>).
set -euo pipefail

PROJECT="${PROJECT:-}"
BOARDS_GLOB="${BOARDS_GLOB:-}"
BUILD_DIR="${BUILD_DIR:-kitium-out/build}"
mkdir -p "${BUILD_DIR}"

# --- Discover boards --------------------------------------------------------
declare -a pcbdocs=()

if [ -n "${BOARDS_GLOB}" ]; then
  # Explicit glob wins.
  while IFS= read -r f; do pcbdocs+=("${f}"); done < <(compgen -G "${BOARDS_GLOB}" || true)
elif [ -n "${PROJECT}" ] && [ -f "${PROJECT}" ] && [[ "${PROJECT}" == *.PcbDoc ]]; then
  pcbdocs+=("${PROJECT}")
else
  # Search a base dir: the project's folder, or the repo root.
  base="."
  if [ -n "${PROJECT}" ]; then
    if [ -d "${PROJECT}" ]; then base="${PROJECT}";
    elif [ -f "${PROJECT}" ]; then base="$(dirname "${PROJECT}")"; fi
  fi
  while IFS= read -r f; do pcbdocs+=("${f}"); done < <(find "${base}" -type f -iname '*.PcbDoc' | sort)
fi

[ "${#pcbdocs[@]}" -gt 0 ] || { echo "[kitium] no .PcbDoc found" >&2; exit 0; }

# --- Convert each board -----------------------------------------------------
for pcb in "${pcbdocs[@]}"; do
  name="$(basename "${pcb}" .PcbDoc)"
  outdir="${BUILD_DIR}/${name}"
  mkdir -p "${outdir}"
  out="${outdir}/${name}.kicad_pcb"

  echo "[kitium] converting: ${pcb} -> ${out}" >&2
  kicad-cli pcb import \
    --format altium \
    --output "${out}" \
    --report-file "${outdir}/import-report.txt" \
    "${pcb}" >&2

  echo "${out}"   # stdout: machine-readable list consumed by entrypoint.sh
done
