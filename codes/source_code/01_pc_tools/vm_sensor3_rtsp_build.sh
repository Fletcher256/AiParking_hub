#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-build}"
BUILD="${BUILD:-/home/ebaina/official_dtof_rtsp_sensor3_20260601}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:${PATH}"
export BUILD ZIP

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
  if [ -f /tmp/rtspserver_overlay.tar ]; then
    tar -xf /tmp/rtspserver_overlay.tar -C "$BUILD/src/rtspserver"
  fi
  if [ -f /tmp/sample_dtof_rtsp_sensor3.c ]; then
    cp /tmp/sample_dtof_rtsp_sensor3.c "$BUILD/src/dtof/sample_dtof.c"
  fi
  if [ -f /tmp/rtsp_server_api.cpp ]; then
    cp /tmp/rtsp_server_api.cpp "$BUILD/src/rtspserver/hisi_sample/rtsp_server_api.cpp"
  fi
  if [ -f /tmp/rtsp_manager.cpp ]; then
    cp /tmp/rtsp_manager.cpp "$BUILD/src/rtspserver/hisi_sample/rtsp_manager.cpp"
  fi
  if [ -f /tmp/rtsp_manager.h ]; then
    cp /tmp/rtsp_manager.h "$BUILD/src/rtspserver/hisi_sample/rtsp_manager.h"
  fi
  if [ -f /tmp/rtsp_server_api.h ]; then
    cp /tmp/rtsp_server_api.h "$BUILD/src/rtspserver/hisi_sample/rtsp_server_api.h"
    cp /tmp/rtsp_server_api.h "$BUILD/include/3rdparty/rtsp_server_api.h"
  fi
  python3 - <<'PY'
from pathlib import Path

p = Path("src/dtof/sample_dtof.c")
text = p.read_text()
old = "case 7: /* 7 sensor0 + dtof0 + rtsp */\n            ret = sample_dtof_dtof_and_rgb(2, dst_ip, TD_TRUE);"
new = "case 7: /* 7 sensor0 + dtof1 + rtsp */\n            ret = sample_dtof_dtof_and_rgb(3, dst_ip, TD_TRUE);"
if old not in text:
    raise SystemExit("case7 RTSP sensor2 pattern not found; upload the RTSP-enabled sample_dtof.c to /tmp/sample_dtof_rtsp_sensor3.c first")
text = text.replace(old, new, 1)
text = text.replace(
    'printf("    (7) sensor0 + dtof0 + rtsp   4lane sensor0 + 1lane sensor2 + rtsp live0.\\n");',
    'printf("    (7) sensor0 + dtof1 + rtsp   4lane sensor0 + 1lane sensor3 + rtsp live0.\\n");',
    1,
)
p.write_text(text)
PY
  printf 'SENSOR3_RTSP_BUILD_DIR=%s\n' "$BUILD"
}

build_all() {
  test -f "$BUILD/src/dtof/sample_dtof.c"
  test -f "$BUILD/src/rtspserver/Makefile"

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
  cp sample_dtof sample_dtof_rtsp_sensor3
  sha256sum sample_dtof_rtsp_sensor3
  ls -l sample_dtof_rtsp_sensor3
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
