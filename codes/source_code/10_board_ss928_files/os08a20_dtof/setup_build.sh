#!/bin/bash
# Cross-compile on Linux/WSL2.
# Usage: ./setup_build.sh <sdk_dir> <open_camera_dir>
# Example:
#   ./setup_build.sh /mnt/d/parking_board_agent/vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master \
#                   /mnt/d/parking_board_agent/vendor/HiEuler_open_camera_fresh_unzip/open_camera-master

SDK_DIR="${1:?Usage: $0 <sdk_dir> <open_camera_dir>}"
OPEN_CAMERA="${2:?Usage: $0 <sdk_dir> <open_camera_dir>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${SDK_DIR}/src/os08a20_dtof"
IMX_DIR="${OPEN_CAMERA}/mipi_rgb_dtof/code/mipi_imx347"

set -e

echo "=== Creating ${TARGET_DIR} ==="
mkdir -p "${TARGET_DIR}"

echo "=== Copying open_camera support files ==="
rsync -a "${IMX_DIR}/scene_auto/"   "${TARGET_DIR}/scene_auto/"
rsync -a "${IMX_DIR}/dtof/"         "${TARGET_DIR}/dtof/"
cp "${IMX_DIR}/dtof_dumpraw.c"      "${TARGET_DIR}/"
cp "${IMX_DIR}/pwm.c"               "${TARGET_DIR}/"

echo "=== Copying our source and Makefile ==="
cp "${SCRIPT_DIR}/os08a20_dtof.c"   "${TARGET_DIR}/"
cp "${SCRIPT_DIR}/Makefile"         "${TARGET_DIR}/"

echo "=== Building (OS_TYPE=openeuler) ==="
cd "${TARGET_DIR}"
make OS_TYPE=openeuler -j4

echo ""
echo "Binary: ${TARGET_DIR}/sample_os08a20_dtof"
echo ""
echo "Deploy with:"
echo "  scp ${TARGET_DIR}/sample_os08a20_dtof root@192.168.137.2:/opt/sample/mipi_rgb_dtof_demo/"
