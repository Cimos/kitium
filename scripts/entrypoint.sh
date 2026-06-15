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
# Capture convert.sh's REAL exit code via a temp file — a command in process
# substitution `< <(...)` hides its status from set -e/mapfile, which would let a
# board that failed AFTER earlier boards succeeded slip through the gate silently.
boards_list="${OUT_DIR}/.boards"
set +e
PROJECT="${PROJECT}" BOARDS_GLOB="${BOARDS_GLOB}" BUILD_DIR="${BUILD_DIR}" \
  "${SCRIPTS}/convert.sh" > "${boards_list}"
conv_rc=$?
set -e
[ "${conv_rc}" -eq 0 ] || fail "Conversion failed (rc=${conv_rc}) — bad/LFS-pointer board or kicad-cli import error (see log above)."
mapfile -t BOARDS < "${boards_list}"
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
preflight_failed=0

# --- 3+4. Per-board outputs + checks ---------------------------------------
for board in "${BOARDS[@]}"; do
  name="$(basename "${board}" .kicad_pcb)"
  bdir="$(dirname "${board}")"   # per-board dir created by convert.sh
  [ -d "${bdir}" ] || fail "internal: expected per-board directory ${bdir}"

  # Altium imports zones UNFILLED — refill before any DRC/plot/render. Capture the
  # python rc via PIPESTATUS (tee would otherwise mask it) and warn loudly: silent
  # refill failure means wrong gerbers/DRC, the exact trap we're guarding against.
  set +e
  python3 "${SCRIPTS}/refill_zones.py" "${board}" 2>&1 | tee -a "${bdir}/kibot.log"
  rfc=${PIPESTATUS[0]}
  set -e
  [ "${rfc}" -eq 0 ] || warn "zone refill FAILED for ${name} (rc=${rfc}) — DRC/gerbers/renders may be wrong"

  # Pre-flight guard: empty board / all-UNK refs are silent-import traps. Fail loud.
  log "Inspecting ${name}"
  if ! python3 "${SCRIPTS}/pcb_inspect.py" "${board}" --metrics-out "${bdir}/metrics.json" --assert; then
    {
      echo "## Board: \`${name}\` — ❌ PRE-FLIGHT FAILED"
      echo
      echo "Conversion produced an unusable board (empty or all-UNK references). See logs."
      echo
    } >> "${REPORT}"
    preflight_failed=1
    continue
  fi

  log "Running KiBot outputs for board: ${name}"
  # KiBot generates gerbers, drill, position, PDF, 3D render and runs DRC. No
  # schematic flag: there's no headless .SchDoc import and the config has no
  # schematic-dependent outputs (BOM is derived from the board by pcb_bom.py below).
  set +e
  kibot -c "${KIBOT_CFG}" -b "${board}" -d "${bdir}/out" 2>&1 | tee -a "${bdir}/kibot.log"
  kibot_rc=${PIPESTATUS[0]}
  set -e
  [ "${kibot_rc}" -eq 0 ] || { warn "KiBot reported issues for ${name} (rc=${kibot_rc}) — see kibot.log"; drc_failed=1; }

  {
    echo "## Board: \`${name}\`"
    echo
    echo "- Artifacts: \`${bdir}/out\`"
    if [ -f "${bdir}/metrics.json" ]; then
      echo "<details><summary>Metrics</summary>"
      echo
      echo '```json'
      cat "${bdir}/metrics.json"
      echo '```'
      echo "</details>"
    fi
    echo
  } >> "${REPORT}"

  # Derive the board BOM ourselves — KiBot's bom output is schematic-only and a
  # board-only import has no schematic. Then cross-check vs Altium's exported BOM
  # (Altium stays the BOM authority for MPN/supplier data).
  if [ -n "${BOM_CSV}" ]; then
    kicad_bom="${bdir}/board-bom.csv"
    python3 "${SCRIPTS}/pcb_bom.py" "${board}" --out "${kicad_bom}" || true
    if [ -f "${kicad_bom}" ]; then
      log "Cross-checking BOM for ${name} against ${BOM_CSV}"
      python3 "${SCRIPTS}/bom_crosscheck.py" \
        --kicad-bom "${kicad_bom}" \
        --altium-bom "${BOM_CSV}" \
        --out "${bdir}/bom-diff.md" || true
      [ -f "${bdir}/bom-diff.md" ] && cat "${bdir}/bom-diff.md" >> "${REPORT}"
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
# Post/update the sticky PR comment (no-op off-PR; never fails the gate).
python3 "${SCRIPTS}/post_comment.py" "${REPORT}" || true

# --- Gate decision ----------------------------------------------------------
# Pre-flight failure means the conversion is unusable — always hard-fail.
if [ "${preflight_failed}" -ne 0 ]; then
  fail "One or more boards failed pre-flight (empty or all-UNK references) — conversion unusable."
fi
if [ "${DRC_MODE}" = "block" ] && [ "${drc_failed}" -ne 0 ]; then
  fail "DRC gate is in 'block' mode and at least one board failed."
fi
log "Done. Report: ${REPORT}"
