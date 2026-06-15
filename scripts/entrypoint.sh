#!/usr/bin/env bash
# Kitium entrypoint: locate -> convert -> kibot -> cross-check -> report.
#
# STATUS: scaffold. The conversion and KiBot invocations are written against
# documented KiCad 9/10 behaviour and will be verified end-to-end in Phase 0.
set -euo pipefail

KITIUM_HOME="${KITIUM_HOME:-/opt/kitium}"
SCRIPTS="${KITIUM_HOME}/scripts"
KIBOT_CFG="${KITIUM_HOME}/kibot/kitium.kibot.yaml"

# --- Inputs (GitHub passes action inputs as INPUT_<NAME>) -------------------
PROJECT="${INPUT_PROJECT:-}"
BOARDS_GLOB="${INPUT_BOARDS_GLOB:-}"
BOM_CSV="${INPUT_BOM_CSV:-}"
DRC_MODE="${INPUT_DRC:-report}"
OUT_DIR="${INPUT_OUTPUT_DIR:-kitium-out}"

BUILD_DIR="${OUT_DIR}/build"
REPORT="${OUT_DIR}/kitium-report.md"
mkdir -p "${BUILD_DIR}"

log()  { printf '\033[1;34m[kitium]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[kitium]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[kitium]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1+2. Locate & convert every board -------------------------------------
# convert.sh writes one <board>.kicad_pcb per Altium .PcbDoc under BUILD_DIR
# and prints the resulting board paths, one per line.
log "Locating and converting Altium boards..."
mapfile -t BOARDS < <(
  PROJECT="${PROJECT}" BOARDS_GLOB="${BOARDS_GLOB}" BUILD_DIR="${BUILD_DIR}" \
    "${SCRIPTS}/convert.sh"
)
[ "${#BOARDS[@]}" -gt 0 ] || fail "No boards were converted — check 'project'/'boards_glob' inputs."
log "Converted ${#BOARDS[@]} board(s)."

# --- Report header ----------------------------------------------------------
{
  echo "# Kitium report"
  echo
  echo "Converted **${#BOARDS[@]}** board(s) from Altium to KiCad."
  echo
} > "${REPORT}"

drc_failed=0

# --- 3+4. Per-board outputs + checks ---------------------------------------
for board in "${BOARDS[@]}"; do
  name="$(basename "${board}" .kicad_pcb)"
  bdir="$(dirname "${board}")"
  log "Running KiBot outputs for board: ${name}"

  # KiBot generates gerbers, renders, board-BOM, diff, and runs DRC.
  # --board-only because we have no schematic (no headless sch import).
  set +e
  kibot -c "${KIBOT_CFG}" -b "${board}" -d "${bdir}/out" --board-only 2>&1 | tee "${bdir}/kibot.log"
  kibot_rc=${PIPESTATUS[0]}
  set -e
  [ "${kibot_rc}" -eq 0 ] || { warn "KiBot reported issues for ${name} (rc=${kibot_rc}) — see kibot.log"; drc_failed=1; }

  {
    echo "## Board: \`${name}\`"
    echo
    echo "- Artifacts: \`${bdir}/out\`"
    echo
  } >> "${REPORT}"

  # BOM cross-check vs Altium's exported BOM (Altium remains the BOM authority).
  if [ -n "${BOM_CSV}" ]; then
    kicad_bom="$(find "${bdir}/out" -name '*bom*.csv' | head -n1 || true)"
    if [ -n "${kicad_bom}" ]; then
      log "Cross-checking BOM for ${name} against ${BOM_CSV}"
      python3 "${SCRIPTS}/bom_crosscheck.py" \
        --kicad-bom "${kicad_bom}" \
        --altium-bom "${BOM_CSV}" \
        --out "${bdir}/bom-diff.md" || true
      cat "${bdir}/bom-diff.md" >> "${REPORT}"
    else
      warn "No KiBot BOM CSV found for ${name}; skipping cross-check."
    fi
  fi
done

# --- 5. Surface the report --------------------------------------------------
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  cat "${REPORT}" >> "${GITHUB_STEP_SUMMARY}"
fi
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "report=${REPORT}" >> "${GITHUB_OUTPUT}"
fi
# TODO(phase 3): post ${REPORT} as a PR comment (needs GITHUB_TOKEN + gh/API).

# --- Gate decision ----------------------------------------------------------
if [ "${DRC_MODE}" = "block" ] && [ "${drc_failed}" -ne 0 ]; then
  fail "DRC gate is in 'block' mode and at least one board failed."
fi
log "Done. Report: ${REPORT}"
