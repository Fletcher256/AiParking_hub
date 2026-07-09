#!/usr/bin/env bash
set -euo pipefail

candidates=(
  /home/ebaina/official_dtof_line_dump_debug_20260602_124406/lib/linux/3rdparty/libdepth_process.a
  /home/ebaina/official_dtof_line_mask_heuristic_20260602_134349/lib/linux/3rdparty/libdepth_process.a
  /home/ebaina/official_dtof_raw16_afterstart_debug_20260602/lib/linux/3rdparty/libdepth_process.a
)

lib=""
for candidate in "${candidates[@]}"; do
  if [[ -f "$candidate" ]]; then
    lib="$candidate"
    break
  fi
done

echo "LIB=$lib"
if [[ -z "$lib" ]]; then
  echo "NO_LIB_FOUND"
  exit 1
fi

if command -v aarch64-mix210-linux-nm >/dev/null 2>&1; then
  nm_cmd=aarch64-mix210-linux-nm
else
  nm_cmd=nm
fi
echo "NM=$nm_cmd"

echo "DEFINED_SYMBOLS_BEGIN"
"$nm_cmd" -g --defined-only "$lib" 2>/dev/null \
  | grep -Ei 'Dtof|Process|Init|data|histo|hist|depth|config|save|load|raw|line|bin|peak' \
  | head -n 240 || true
echo "DEFINED_SYMBOLS_END"

echo "DEFINED_SYMBOLS_DEMANGLED_TARGETS_BEGIN"
"$nm_cmd" -A -C --defined-only "$lib" 2>/dev/null \
  | grep -E 'LoadHistoData|SaveBinFile|SaveOutPut|Processor::Process|HistoProc::Run|HistoInfo|PileUp::ConfigSwitch|GetFactorPs|GetTdcTimeBin|GetTotalShotNum' \
  | head -n 260 || true
echo "DEFINED_SYMBOLS_DEMANGLED_TARGETS_END"

echo "ARCHIVE_OBJECTS_BEGIN"
ar t "$lib" | grep -Ei 'data|proc|histo|udp|io|processor|pile' || true
echo "ARCHIVE_OBJECTS_END"

echo "UNDEFINED_SYMBOLS_BEGIN"
"$nm_cmd" -u "$lib" 2>/dev/null \
  | grep -Ei 'ini|file|malloc|memcpy|printf|log|eeprom|temperature|raw|line|depth|hist|config' \
  | head -n 240 || true
echo "UNDEFINED_SYMBOLS_END"

echo "STRINGS_BEGIN"
strings "$lib" \
  | grep -Ei 'Dtof|Process|Histo|hist|depth|distance|config|switch|500|1000|bin|peak|shot|pseudo|temperature|sentinel|line|raw|threshold|pile|fwhm|prob|noise' \
  | head -n 360 || true
echo "STRINGS_END"
