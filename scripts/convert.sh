#!/usr/bin/env bash
# Locate Altium .PcbDoc files and convert each to KiCad with kicad-cli.
# Prints the resulting .kicad_pcb paths (one per line) on stdout.
#
# Inputs via env: PROJECT, BOARDS_GLOB, BUILD_DIR
#
# Verified in Phase 0: `kicad-cli pcb import --format altium --output <out>
# --report-format json --report-file <f> <input>` on KiCad 10 (kicad/kicad:10.0.0-full).
set -euo pipefail
shopt -s globstar nullglob   # so a recursive boards_glob (**/*.PcbDoc) works as expected

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

# Exit NONZERO on no boards so the caller can distinguish "found nothing" from
# success (the caller can't read our exit code through stdout otherwise).
[ "${#pcbdocs[@]}" -gt 0 ] || { echo "[kitium] no .PcbDoc found (project='${PROJECT}' glob='${BOARDS_GLOB}')" >&2; exit 2; }

# Guard: a Git LFS pointer (or HTML redirect) is NOT a real board. Real Altium
# files are OLE/CFB compound docs starting with magic D0CF11E0A1B11AE1. Feeding a
# pointer to kicad-cli is a silent failure, so we reject it up front.
assert_real_pcbdoc() {
  local f="$1"
  if head -c 64 "${f}" | grep -qa 'git-lfs.github.com/spec'; then
    echo "[kitium] ERROR: ${f} is an unresolved Git LFS pointer, not a board." >&2
    echo "[kitium]        Materialize it on the runner (git lfs pull / lfs: true) before Kitium runs." >&2
    return 1
  fi
  local magic; magic=$(od -An -tx1 -N8 "${f}" 2>/dev/null | tr -d ' \n')
  if [ "${magic}" != "d0cf11e0a1b11ae1" ]; then
    echo "[kitium] ERROR: ${f} is not an OLE/CFB Altium binary (magic='${magic}')." >&2
    return 1
  fi
}

# --- Convert each board -----------------------------------------------------
for pcb in "${pcbdocs[@]}"; do
  assert_real_pcbdoc "${pcb}" || exit 1
  name="$(basename "${pcb}" .PcbDoc)"
  outdir="${BUILD_DIR}/${name}"
  mkdir -p "${outdir}"
  out="${outdir}/${name}.kicad_pcb"

  echo "[kitium] converting: ${pcb} -> ${out}" >&2
  # --report-format json captures importer diagnostics as part of validation.
  kicad-cli pcb import \
    --format altium \
    --output "${out}" \
    --report-format json \
    --report-file "${outdir}/import-report.json" \
    "${pcb}" >&2

  # Record the source .PcbDoc (repo-relative, no leading ./) so entrypoint.sh can
  # fetch the board's BASE revision from git history for the visual diff.
  printf '%s\n' "${pcb#./}" > "${outdir}/.source"

  echo "${out}"   # stdout: machine-readable list consumed by entrypoint.sh
done
