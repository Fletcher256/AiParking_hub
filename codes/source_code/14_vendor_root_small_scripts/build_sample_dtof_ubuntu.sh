#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof"

# The official Makefile defaults to aarch64-mix210-linux- for Linux.
# If your Ubuntu VM uses another prefix, pass it explicitly, for example:
#   CROSS_COMPILE=aarch64-mix210-linux- ./vendor/build_sample_dtof_ubuntu.sh
#   CROSS_COMPILE=arm-openeuler-linux-gnueabi- OS_TYPE=openeuler ./vendor/build_sample_dtof_ubuntu.sh
make clean || true
make OS_TYPE="${OS_TYPE:-linux}" CROSS_COMPILE="${CROSS_COMPILE:-aarch64-mix210-linux-}"
file sample_dtof
