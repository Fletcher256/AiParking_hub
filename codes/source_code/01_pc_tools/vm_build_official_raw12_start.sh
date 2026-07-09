#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_raw12_start_debug_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_raw12_start_dbg}"
RAW12_EXTRA_CFLAGS="${RAW12_EXTRA_CFLAGS:--DDTOF_RAW12_START_OFFICIAL -DDTOF_DUMP_SOURCE=0}"
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

cp /tmp/official_sample_dtof_raw12_start_debug.c "$BUILD/src/dtof/sample_dtof.c"
cp /tmp/official_dtof_dumpraw_raw12_start_debug.c "$BUILD/src/dtof/dtof_dumpraw.c"

python3 - <<'PY'
from pathlib import Path

sample = Path("src/dtof/sample_dtof.c")
text = sample.read_text()
old_pool = (
    "    /* default raw pool: raw12bpp + compress_line */\n"
    "    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;\n"
    "    buf_attr.compress_mode = (video_mode == OT_VI_VIDEO_MODE_NORM ? OT_COMPRESS_MODE_LINE : OT_COMPRESS_MODE_NONE);\n"
)
new_pool = (
    "    /* raw12bpp + no compression for GS1860 startup diagnostic. */\n"
    "    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_12;\n"
    "    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;\n"
    "    buf_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
)
if old_pool not in text:
    raise SystemExit("raw pool block not found")
text = text.replace(old_pool, new_pool, 1)

needle = "        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;\n"
replacement = (
    needle
    + "        vi_cfg->pipe_info[0].pipe_attr.bit_width = OT_DATA_BIT_WIDTH_12;\n"
    + "        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;\n"
    + "        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
)
count = text.count(needle)
if count < 2:
    raise SystemExit(f"expected at least two GS1860 pipe blocks, found {count}")
text = text.replace(needle, replacement)
sample.write_text(text)

dump = Path("src/dtof/dtof_dumpraw.c")
dump_text = dump.read_text()
old_dump = "    td_u32 u32nbit = 10;\n"
if old_dump not in dump_text:
    raise SystemExit("dump bit-width block not found")
dump_text = dump_text.replace(old_dump, "    td_u32 u32nbit = 12;\n", 1)
dump.write_text(dump_text)

print(f"RAW12_START_PATCH pipe_blocks={count}")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_raw12_start_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$RAW12_EXTRA_CFLAGS" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_raw12_start_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
if strings "$BINARY_NAME" | grep -q sensor3_j4_cfg; then
  echo "unexpected j4cfg string in raw12-start binary" >&2
  exit 5
fi
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
