#!/usr/bin/env bash
set -euo pipefail

variant="${1:?usage: vm_build_dtof_dump_variant.sh pipe|feout|bas|unpack10|raw10none|raw12none|postraw10none|near500}"
case "$variant" in
  pipe) dump_source=0; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="" ;;
  feout) dump_source=1; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="" ;;
  bas) dump_source=2; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="" ;;
  unpack10) dump_source=0; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="-DDTOF_FORCE_UNPACK_10BIT" ;;
  raw10none) dump_source=0; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="-DDTOF_FORCE_RAW10_NONE" ;;
  raw12none) dump_source=0; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="-DDTOF_FORCE_RAW12_NONE" ;;
  postraw10none) dump_source=0; keep_flag=""; force_flags="" ;;
  near500) dump_source=0; keep_flag="-DDTOF_KEEP_PIPE_ATTR"; force_flags="-DDTOF_FORCE_UNPACK_10BIT -DDTOF_FORCE_500PS_CONFIG" ;;
  *) echo "unknown variant: $variant" >&2; exit 2 ;;
esac

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_rtsp_sensor3_${variant}_${timestamp}}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

chmod +x /tmp/vm_sensor3_rtsp_build.sh
BUILD="$BUILD" /tmp/vm_sensor3_rtsp_build.sh prepare

cp /tmp/dtof_dumpraw_dumpselect.c "$BUILD/src/dtof/dtof_dumpraw.c"
cp /tmp/dtof_Makefile_extra_cflags "$BUILD/src/dtof/Makefile"

cd "$BUILD/src/rtspserver"
env PATH="$TOOLCHAIN" make clean >/tmp/rtsp_clean_${variant}.log
env PATH="$TOOLCHAIN" make AR=aarch64-mix210-linux-ar all >/tmp/rtsp_build_${variant}.log
cp libxoprtsp.a "$BUILD/lib/linux/3rdparty/libxoprtsp.a"

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_clean_${variant}.log
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="${keep_flag} -DDTOF_DUMP_SOURCE=${dump_source} ${force_flags}" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_${variant}_build.log >/dev/null

binary="sample_dtof_rtsp_sensor3_${variant}_dbg"
cp sample_dtof "$binary"
sha256sum "$binary"
ls -l "$binary"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$binary"
