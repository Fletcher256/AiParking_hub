#!/bin/bash
# Board-native build: run from Windows PC (Git Bash/WSL/Linux).
# Assumes gcc is available on the board (yum install gcc if not).
#
# Usage: ./deploy_and_build.sh [board_ip]
# Default board IP: 192.168.137.2

BOARD_IP="${1:-192.168.137.2}"
BOARD="root@${BOARD_IP}"
BUILD_DIR="/opt/build/os08a20_dtof"
DEPLOY_DIR="/opt/sample/mipi_rgb_dtof_demo"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENDOR_DIR="${SCRIPT_DIR}/../../vendor"
IMX_DIR="${VENDOR_DIR}/HiEuler_open_camera_fresh_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347"
SDK_LIB="${VENDOR_DIR}/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/lib/linux/hisilicon"
SDK_INC="${VENDOR_DIR}/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/include/hisilicon"
COMMON_DIR="${VENDOR_DIR}/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/common"

set -e

echo "=== [1/6] Prepare build tree on board ==="
ssh "$BOARD" "rm -rf ${BUILD_DIR} && mkdir -p ${BUILD_DIR}/sensor/lib ${BUILD_DIR}/dtof/lib ${BUILD_DIR}/dtof/include"

echo "=== [2/6] Copy scene_auto and dToF sources ==="
rsync -a "${IMX_DIR}/scene_auto/"        "${BOARD}:${BUILD_DIR}/scene_auto/"
rsync -a "${IMX_DIR}/dtof/include/"      "${BOARD}:${BUILD_DIR}/dtof/include/"
rsync -a "${IMX_DIR}/dtof/lib/"          "${BOARD}:${BUILD_DIR}/dtof/lib/"
scp "${IMX_DIR}/dtof_dumpraw.c"          "${BOARD}:${BUILD_DIR}/"
scp "${IMX_DIR}/pwm.c"                   "${BOARD}:${BUILD_DIR}/"

echo "=== [3/6] Copy SDK headers and common sources ==="
rsync -a "${SDK_INC}/"                   "${BOARD}:${BUILD_DIR}/include/hisilicon/"
rsync -a "${VENDOR_DIR}/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/include/3rdparty/" \
    "${BOARD}:${BUILD_DIR}/include/3rdparty/"
rsync -a "${COMMON_DIR}/"                "${BOARD}:${BUILD_DIR}/common/"

echo "=== [4/6] Copy SDK libraries ==="
scp "${SDK_LIB}/"*.a                     "${BOARD}:${BUILD_DIR}/lib/" 2>/dev/null || \
rsync -a "${SDK_LIB}/"                   "${BOARD}:${BUILD_DIR}/lib/"
# OS08A20 sensor lib is already in SDK lib dir; no separate copy needed

echo "=== [5/6] Copy our source and standalone Makefile ==="
scp "${SCRIPT_DIR}/os08a20_dtof.c"       "${BOARD}:${BUILD_DIR}/"
scp "${SCRIPT_DIR}/Makefile.standalone"  "${BOARD}:${BUILD_DIR}/Makefile"

echo "=== [6/6] Build on board ==="
ssh "$BOARD" "cd ${BUILD_DIR} && make -j2 2>&1 | tail -40"

echo ""
echo "Deploying binary to ${DEPLOY_DIR}..."
ssh "$BOARD" "mkdir -p ${DEPLOY_DIR} && cp ${BUILD_DIR}/sample_os08a20_dtof ${DEPLOY_DIR}/"
echo "Done: ${DEPLOY_DIR}/sample_os08a20_dtof"
