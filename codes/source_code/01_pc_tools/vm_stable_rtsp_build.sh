#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-build}"
BUILD="${BUILD:-/home/ebaina/official_dtof_rtsp_stable_20260601}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:${PATH}"

prepare() {
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
  test -f "$BUILD/src/rtspserver/Makefile"
  printf 'STABLE_BUILD_DIR=%s\n' "$BUILD"
}

build_all() {
  test -f "$BUILD/src/dtof/sample_dtof.c"
  test -f "$BUILD/src/common/sample_comm_venc.c"
  test -f "$BUILD/src/rtspserver/hisi_sample/rtsp_manager.cpp"

  cd "$BUILD/src/rtspserver"
  PATH="$TOOLCHAIN" make clean
  PATH="$TOOLCHAIN" make AR=aarch64-mix210-linux-ar all
  cp libxoprtsp.a "$BUILD/lib/linux/3rdparty/libxoprtsp.a"

  cd "$BUILD/src/dtof"
  PATH="$TOOLCHAIN" make clean
  PATH="$TOOLCHAIN" make OS_TYPE=linux \
    EXTRA_CFLAGS=-DDTOF_KEEP_PIPE_ATTR \
    SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
    SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
    SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
    SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
    all
  cp sample_dtof sample_dtof_rtsp_stable
  sha256sum sample_dtof_rtsp_stable
  ls -l sample_dtof_rtsp_stable
}

case "$ACTION" in
  prepare)
    prepare
    ;;
  build)
    build_all
    ;;
  *)
    echo "usage: $0 {prepare|build}" >&2
    exit 2
    ;;
esac
