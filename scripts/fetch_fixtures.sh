#!/usr/bin/env bash
# Fetch real Altium test fixtures for local development.
#
# These come from KiCad's own Altium-importer regression suite. As committed into
# KiCad they are GPLv3, so we DO NOT vendor them — they are downloaded on demand
# into ./fixtures/ (gitignored). For anything that must be committed, use a
# permissively-licensed project instead (e.g. venky-vn/STM32_BLUEPILL, MPL-2.0).
set -euo pipefail

BASE="https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/qa/data/pcbnew/plugins/altium"
DEST="${1:-fixtures}"
mkdir -p "${DEST}"

# Relative paths under the altium fixture dir.
FILES=(
  "eDP_adapter_dvt1_source/eDP_adapter_dvt1.PrjPcb"
  "eDP_adapter_dvt1_source/eDP_adapter_dvt1.PcbDoc"
  "eDP_adapter_dvt1_source/it6251_core.SchDoc"
  "eDP_adapter_dvt1_source/power.SchDoc"
  "HiFive/HiFive1.B01.PcbDoc"
)

# OLE/CFB compound-file magic — real .PcbDoc/.SchDoc must start with this.
OLE_MAGIC="d0cf11e0a1b11ae1"

ok=0; bad=0
for rel in "${FILES[@]}"; do
  out="${DEST}/${rel}"
  mkdir -p "$(dirname "${out}")"
  url="${BASE}/${rel}"
  echo "[kitium] fetching ${rel}"
  if ! curl -fsSL "${url}" -o "${out}"; then
    echo "  ✗ download failed: ${url}" >&2; bad=$((bad+1)); continue
  fi
  size=$(wc -c < "${out}")
  case "${rel}" in
    *.PcbDoc|*.SchDoc)
      magic=$(od -An -tx1 -N8 "${out}" 2>/dev/null | tr -d ' \n')
      if [ "${magic}" = "${OLE_MAGIC}" ]; then
        echo "  ✓ OLE binary OK (${size} bytes)"; ok=$((ok+1))
      else
        echo "  ✗ NOT an OLE file (got magic '${magic}') — likely an HTML/LFS-pointer redirect" >&2
        bad=$((bad+1))
      fi
      ;;
    *)
      # .PrjPcb is a text/INI project file, not OLE — just sanity-check size.
      echo "  ✓ text project file (${size} bytes)"; ok=$((ok+1))
      ;;
  esac
done

echo "[kitium] fixtures: ${ok} ok, ${bad} failed -> ${DEST}/"
[ "${bad}" -eq 0 ]
