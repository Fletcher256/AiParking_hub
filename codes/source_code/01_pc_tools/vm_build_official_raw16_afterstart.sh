#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_raw16_afterstart_debug_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_raw16_afterstart_dbg}"
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

cp /tmp/dtof_dumpraw_keepattr_compressparam.c "$BUILD/src/dtof/dtof_dumpraw.c"

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
    "    /* raw16bpp + no compression for dynamic_blc-style dToF dump diagnostic. */\n"
    "    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_16;\n"
    "    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_16BPP;\n"
    "    buf_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
)
if old_pool not in text:
    raise SystemExit("raw pool block not found")
text = text.replace(old_pool, new_pool, 1)
sample.write_text(text)

dump = Path("src/dtof/dtof_dumpraw.c")
dump_text = dump.read_text()
old_bit = "    td_u32 u32nbit = 10;\n"
if old_bit not in dump_text:
    raise SystemExit("dump bit-width block not found")
dump_text = dump_text.replace(old_bit, "    td_u32 u32nbit = 16;\n", 1)

old_set = (
    "        ret = ss_mpi_vi_set_pipe_attr(bind_pipe->pipe_id[i], &pipe_attr);\n"
    "        if (ret != TD_SUCCESS) {\n"
    "            printf(\"set vi_pipe %d attr failed!\\n\", bind_pipe->pipe_id[i]);\n"
    "            return ret;\n"
    "        }\n"
)
new_set = old_set + (
    "        printf(\"[DTOF_DBG] dump_source=%s set vi_pipe %d attr pixfmt=%d compress=%d rawdepth=%u\\n\",\n"
    "            dtof_dump_source_name(), bind_pipe->pipe_id[i], pipe_attr.pixel_format,\n"
    "            pipe_attr.compress_mode, u32rawdepth);\n"
)
if old_set not in dump_text:
    raise SystemExit("set pipe attr block not found")
dump_text = dump_text.replace(old_set, new_set, 1)
dump.write_text(dump_text)

print("RAW16_AFTERSTART_PATCH applied")
PY

python3 - <<'PY'
from pathlib import Path

makefile = Path("src/dtof/Makefile")
text = makefile.read_text()
if "CFLAGS += $(EXTRA_CFLAGS)" not in text:
    marker = "MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a\n"
    if marker not in text:
        raise SystemExit("Makefile marker not found")
    text = text.replace(marker, marker + "\nCFLAGS += $(EXTRA_CFLAGS)\n", 1)
    makefile.write_text(text)
    print("RAW16_AFTERSTART_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("RAW16_AFTERSTART_PATCH EXTRA_CFLAGS hook already present")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_raw16_afterstart_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="-DDTOF_DUMP_SOURCE=0" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_raw16_afterstart_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
