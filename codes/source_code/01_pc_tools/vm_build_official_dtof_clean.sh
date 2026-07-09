#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_clean_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export BUILD ZIP

mkdir -p "$BUILD"
cd "$BUILD"

python3 - <<'PY'
import os
import zipfile
from pathlib import Path

build = Path(os.environ["BUILD"])
zip_path = Path(os.environ["ZIP"])
with zipfile.ZipFile(zip_path) as zf:
    for member in zf.infolist():
        normalized = member.filename.replace("\\", "/")
        if not normalized:
            continue
        target = build / normalized
        if member.is_dir() or normalized.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open("wb") as dst:
            dst.write(src.read())
PY

test -f "$BUILD/src/dtof/sample_dtof.c"
test -f "$BUILD/src/dtof/dtof_dumpraw.c"
if [ -f /tmp/official_dtof_dumpraw_debug.c ]; then
  cp /tmp/official_dtof_dumpraw_debug.c "$BUILD/src/dtof/dtof_dumpraw.c"
fi
if [ -f /tmp/official_sample_dtof_debug.c ]; then
  cp /tmp/official_sample_dtof_debug.c "$BUILD/src/dtof/sample_dtof.c"
fi

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_official_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_official_clean_build.log >/dev/null

cp sample_dtof sample_dtof_official_clean
sha256sum sample_dtof_official_clean
ls -l sample_dtof_official_clean
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/sample_dtof_official_clean"
