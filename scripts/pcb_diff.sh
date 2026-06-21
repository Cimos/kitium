#!/usr/bin/env bash
# Best-effort visual PCB diff of a board vs its PR-base revision.
#
# KiCad files are ephemeral (regenerated each run, never committed), so we can't
# git-diff them — only the Altium .PcbDoc is in history. We therefore fetch the base
# revision's .PcbDoc from git, convert it the same way as head, refill its zones (so
# the comparison is apples-to-apples), and run KiBot's file-vs-file diff.
#
# NEVER gates: always exits 0. A missing base board (newly added), a conversion
# failure, or a diff failure is a logged note, not an error.
#
# Usage: pcb_diff.sh <head.kicad_pcb> <source.PcbDoc repo-rel> <base_ref> <kibot_cfg> <out_dir> <scripts_dir>
set -uo pipefail

head_pcb="${1:?head board}"
src="${2:?source .PcbDoc}"
base_ref="${3:-}"
cfg="${4:?kibot config}"
outdir="${5:?out dir}"
scripts="${6:?scripts dir}"

[ -n "${base_ref}" ] || { echo "[kitium] diff: no PR base ref — skipping"; exit 0; }

# Did this board exist at the base revision? (A newly added board has nothing to diff.)
if ! git cat-file -e "${base_ref}:${src}" 2>/dev/null; then
  echo "[kitium] diff: ${src} absent at base ${base_ref:0:8} (new board) — skipping"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

if ! git show "${base_ref}:${src}" > "${tmp}/base.PcbDoc" 2>/dev/null; then
  echo "[kitium] WARN: diff: could not read base board from git — skipping" >&2; exit 0
fi
if ! kicad-cli pcb import --format altium --output "${tmp}/base.kicad_pcb" "${tmp}/base.PcbDoc" >/dev/null 2>&1; then
  echo "[kitium] WARN: diff: base board conversion failed — skipping" >&2; exit 0
fi
# Match head's preprocessing (head was zone-refilled before its outputs).
python3 "${scripts}/refill_zones.py" "${tmp}/base.kicad_pcb" >/dev/null 2>&1 || true

# KiBot doesn't expand env vars in the diff `old:` field, so sed the base file path
# into a temp copy of the config in place of the KITIUM_DIFF_OLD_PATH placeholder.
diff_cfg="${tmp}/diff.yaml"
sed "s#KITIUM_DIFF_OLD_PATH#${tmp}/base.kicad_pcb#" "${cfg}" > "${diff_cfg}"

if kibot -c "${diff_cfg}" -b "${head_pcb}" -d "${outdir}" pcb_diff >/dev/null 2>&1; then
  echo "[kitium] diff: generated vs base ${base_ref:0:8}"
else
  echo "[kitium] WARN: diff generation failed (best-effort, not gating)" >&2
fi
exit 0
