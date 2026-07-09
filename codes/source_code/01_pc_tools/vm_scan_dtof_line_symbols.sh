#!/usr/bin/env bash
set -euo pipefail

sdk="${1:-/home/ebaina/official_dtof_raw16_afterstart_debug_20260602}"
libdir="$sdk/lib/linux/hisilicon"

if [[ ! -d "$libdir" ]]; then
  echo "MISSING_LIBDIR $libdir"
  exit 2
fi

echo "SDK=$sdk"
echo "LIBDIR=$libdir"
echo

echo "## Candidate libraries"
find "$libdir" -maxdepth 1 -type f \( -name '*.so' -o -name '*.a' \) -printf '%f\n' \
  | grep -Ei 'raw|compress|vgs|tde|vi|mpi|isp|sys|mcf' \
  | sort || true
echo

echo "## Exported symbols"
for so in libss_mpi.so libss_isp.so libss_tde.so libss_mcf_vi.so libss_vgs.so; do
  p="$libdir/$so"
  [[ -f "$p" ]] || continue
  echo "### $so"
  nm -D --defined-only "$p" 2>/dev/null \
    | grep -Ei 'compress|decompress|raw|line|pipe' \
    | head -160 || true
  echo
done

echo "## String matches"
for so in libss_mpi.so libss_isp.so libss_tde.so libss_mcf_vi.so libss_vgs.so; do
  p="$libdir/$so"
  [[ -f "$p" ]] || continue
  echo "### $so"
  strings "$p" \
    | grep -Ei 'compress|decompress|raw frame|raw_frame|line compress|compress_param|get_pipe_compress|send_pipe_raw' \
    | head -220 || true
  echo
done
