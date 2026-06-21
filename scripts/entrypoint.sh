#!/usr/bin/env bash
# Kitium entrypoint: locate -> convert -> kibot -> cross-check -> report.
#
# Verified end-to-end in Phase 0/2 on real Altium fixtures (eDP_adapter_dvt1,
# HiFive1.B01) against the pinned KiCad-10 image. See docs/phase0-findings.md.
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
MODE="${INPUT_MODE:-gate}"

BUILD_DIR="${OUT_DIR}/build"
REPORT="${OUT_DIR}/kitium-report.md"
mkdir -p "${BUILD_DIR}"

log()  { printf '\033[1;34m[kitium]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[kitium]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[kitium]\033[0m %s\n' "$*" >&2; exit 1; }

# --- comment mode: post a pre-generated report, nothing else ----------------
# Used by the fork-safe companion workflow (workflow_run), which runs with a
# pull-requests:write token but processes no design files. It downloads the
# report artifact produced by the read-only analysis job and posts it here.
if [ "${MODE}" = "comment" ]; then
  report="${INPUT_REPORT_FILE:-${REPORT}}"
  [ -f "${report}" ] || fail "comment mode: report file not found: ${report}"
  log "Comment mode: posting ${report} to PR #${INPUT_PR_NUMBER:-(from event)}"
  KITIUM_PR_NUMBER="${INPUT_PR_NUMBER:-}" python3 "${SCRIPTS}/post_comment.py" "${report}"
  exit 0
fi

# Validate the gate switch up front: an unrecognised value (typo like "Block",
# "blocking") must NOT silently fall through to non-blocking 'report' — that would
# give a green check on a board with real DRC errors, the exact failure we prevent.
case "${DRC_MODE}" in
  report|block) ;;
  *) fail "Invalid 'drc' input '${DRC_MODE}' (expected 'report' or 'block')." ;;
esac

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

# PR base revision SHA for the visual diff (empty off-PR). The consuming workflow
# checks out with fetch-depth:0, so this commit is reachable in the runner.
BASE_REF=""
if [ -n "${GITHUB_EVENT_PATH:-}" ] && [ -f "${GITHUB_EVENT_PATH}" ]; then
  BASE_REF="$(python3 -c "import json,os;e=json.load(open(os.environ['GITHUB_EVENT_PATH']));print((e.get('pull_request') or {}).get('base',{}).get('sha','') or '')" 2>/dev/null || true)"
fi

# --- 3+4. Per-board outputs + checks ---------------------------------------
for board in "${BOARDS[@]}"; do
  name="$(basename "${board}" .kicad_pcb)"
  bdir="$(dirname "${board}")"   # per-board dir created by convert.sh
  [ -d "${bdir}" ] || fail "internal: expected per-board directory ${bdir}"

  # Apply the real Altium design rules that kicad-cli drops (pour min copper width,
  # clearances) BEFORE refilling, so the re-poured copper matches Altium instead of
  # KiCad's defaults. Reads them from the source .PcbDoc. Best-effort: never gates.
  if [ -f "${bdir}/.source" ]; then
    python3 "${SCRIPTS}/altium_rules.py" "$(cat "${bdir}/.source")" --apply "${board}" \
      --json-out "${bdir}/altium-rules.json" 2>&1 | tee -a "${bdir}/kibot.log" || true
  fi

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
  [ "${kibot_rc}" -eq 0 ] || warn "KiBot exited non-zero for ${name} (rc=${kibot_rc}) — see kibot.log (DRC dont_stop is expected)"

  # Gate signal: count POST-FILTER DRC errors from the JSON report (not kibot's rc,
  # which is 0 under dont_stop). We expect exactly one DRC JSON per board; zero or
  # several means we can't trust the count, so fail closed. (find order is unsorted,
  # so never just head -1 — that could pick the wrong file silently.)
  mapfile -t drc_jsons < <(find "${bdir}/out/drc" -name '*.json' 2>/dev/null | sort)
  if [ "${#drc_jsons[@]}" -eq 1 ]; then
    set +e
    python3 "${SCRIPTS}/drc_gate.py" "${drc_jsons[0]}" \
      --summary-out "${bdir}/drc-summary.txt" --md-out "${bdir}/drc-table.md"
    drc_rc=$?
    set -e
    [ "${drc_rc}" -eq 0 ] || { warn "${name}: post-filter DRC violations present (see drc-summary.txt)"; drc_failed=1; }
  elif [ "${#drc_jsons[@]}" -eq 0 ]; then
    warn "${name}: no DRC JSON report found — cannot verify DRC"; drc_failed=1
  else
    warn "${name}: ${#drc_jsons[@]} DRC JSON reports found (expected 1) — cannot disambiguate, failing closed"; drc_failed=1
  fi

  # Best-effort 3D render (never gates; render_board.sh always exits 0).
  bash "${SCRIPTS}/render_board.sh" "${board}" "${bdir}/out/docs/${name}-3d.png" 2>&1 | tee -a "${bdir}/kibot.log" || true

  # Best-effort visual diff vs the PR base (never gates; pcb_diff.sh always exits 0).
  if [ -f "${bdir}/.source" ]; then
    bash "${SCRIPTS}/pcb_diff.sh" "${board}" "$(cat "${bdir}/.source")" "${BASE_REF}" \
      "${KIBOT_CFG}" "${bdir}/out" "${SCRIPTS}" 2>&1 | tee -a "${bdir}/kibot.log" || true
    # Rasterize the diff PDF to PNG so reviewers can see the change without opening a
    # PDF (poppler's pdftoppm; best-effort). Inline-embedding the PNG in the comment
    # needs image hosting — pending a decision; for now it ships in the artifact.
    if [ -d "${bdir}/out/diff" ]; then
      diff_pdf_raw="$(find "${bdir}/out/diff" -name '*.pdf' 2>/dev/null | sort | head -1)"
      if [ -n "${diff_pdf_raw}" ]; then
        if pdftoppm -png -r 120 "${diff_pdf_raw}" "${bdir}/out/diff/${name}-diff" >/dev/null 2>&1; then
          echo "[kitium] diff PNG(s) rendered"
        else
          warn "${name}: diff PDF->PNG failed (best-effort)"
        fi
      fi
    fi
  fi

  {
    echo "## Board: \`${name}\`"
    echo
    echo "- Artifacts: \`${bdir}/out\`"
    if [ -f "${bdir}/drc-table.md" ]; then
      echo
      cat "${bdir}/drc-table.md"
      echo
    elif [ -f "${bdir}/drc-summary.txt" ]; then
      echo "- DRC (post-filter): $(head -1 "${bdir}/drc-summary.txt")"
    fi
    # Images referenced by LOCAL path (relative to this report's dir). On a PR,
    # post_comment.py uploads them and rewrites the link to a hosted URL so they show
    # inline; off-PR / if hosting fails they degrade to a plain note.
    if [ -f "${bdir}/out/docs/${name}-3d.png" ]; then
      echo
      echo "![3D render: ${name}](build/${name}/out/docs/${name}-3d.png)"
    fi
    if [ -d "${bdir}/out/diff" ]; then
      dpng="$(find "${bdir}/out/diff" -name '*.png' 2>/dev/null | sort | head -1)"
      if [ -n "${dpng}" ]; then
        echo
        echo "![Board diff vs PR base: ${name}](build/${name}/out/diff/$(basename "${dpng}"))"
      fi
    fi
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
  # board-only import has no schematic. Always generate it: it's a useful artifact in
  # its own right and is the input the Phase 4 cross-check will consume.
  kicad_bom="${bdir}/board-bom.csv"
  python3 "${SCRIPTS}/pcb_bom.py" "${board}" --out "${kicad_bom}" || warn "${name}: board BOM generation failed"
  [ -f "${kicad_bom}" ] && echo "- Board BOM: \`${kicad_bom}\`" >> "${REPORT}"

  # Cross-check vs the Altium golden BOM only when one is supplied (Altium stays the
  # BOM authority for MPN/supplier data). Cross-check tuning is Phase 4.
  if [ -n "${BOM_CSV}" ] && [ -f "${kicad_bom}" ]; then
    log "Cross-checking BOM for ${name} against ${BOM_CSV}"
    python3 "${SCRIPTS}/bom_crosscheck.py" \
      --kicad-bom "${kicad_bom}" \
      --altium-bom "${BOM_CSV}" \
      --out "${bdir}/bom-diff.md" || true
    [ -f "${bdir}/bom-diff.md" ] && cat "${bdir}/bom-diff.md" >> "${REPORT}"
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
