#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_raw10_create_clean_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_raw10_create_clean}"
EXTRA="${EXTRA_CFLAGS:--DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN}"
DTOF_DUMPRAW_DEBUG_SRC="${DTOF_DUMPRAW_DEBUG_SRC:-}"
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

if [ -n "$DTOF_DUMPRAW_DEBUG_SRC" ]; then
  test -f "$DTOF_DUMPRAW_DEBUG_SRC"
  cp "$DTOF_DUMPRAW_DEBUG_SRC" "$BUILD/src/dtof/dtof_dumpraw.c"
  echo "RAW10_CREATE_PATCH copied dtof_dumpraw debug source: $DTOF_DUMPRAW_DEBUG_SRC"
fi

python3 - <<'PY'
from pathlib import Path

sample = Path("src/dtof/sample_dtof.c")
text = sample.read_text(encoding="utf-8", errors="replace")

rtsp_line = "    rtsp_set_client_event_cb(sample_dtof_rtsp_client_event);\n"
if rtsp_line in text:
    text = text.replace(
        rtsp_line,
        "    /* Disabled for this VM toolchain: old libxoprtsp.a lacks rtsp_set_client_event_cb. */\n",
        1,
    )

old_sig = (
    "static td_void sample_dtof_get_default_vb_config(ot_size *size, ot_vb_cfg *vb_cfg, "
    "ot_vi_video_mode video_mode,\n"
    "    td_u32 yuv_cnt, td_u32 raw_cnt)\n"
)
new_sig = (
    "static td_void sample_dtof_get_default_vb_config(sample_sns_type sns_type, ot_size *size, "
    "ot_vb_cfg *vb_cfg,\n"
    "    ot_vi_video_mode video_mode, td_u32 yuv_cnt, td_u32 raw_cnt)\n"
)
if old_sig not in text:
    raise SystemExit("vb config signature anchor not found")
text = text.replace(old_sig, new_sig, 1)

old_call = "    sample_dtof_get_default_vb_config(&size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);\n"
new_call = "    sample_dtof_get_default_vb_config(sns_type, &size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);\n"
if old_call not in text:
    raise SystemExit("vb config call anchor not found")
text = text.replace(old_call, new_call, 1)

vb_raw_anchor = (
    "    /* default raw pool: raw12bpp + compress_line */\n"
    "    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;\n"
    "    buf_attr.compress_mode = (video_mode == OT_VI_VIDEO_MODE_NORM ? OT_COMPRESS_MODE_LINE : OT_COMPRESS_MODE_NONE);\n"
)
vb_raw_repl = vb_raw_anchor + (
    "#ifdef DTOF_FORCE_RAW10_NONE\n"
    "    if (sns_type == HISI_GS1860_MIPI_1M_30FPS_10BIT) {\n"
    "        buf_attr.bit_width = OT_DATA_BIT_WIDTH_10;\n"
    "        buf_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;\n"
    "        buf_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
    "    }\n"
    "#endif\n"
)
if vb_raw_anchor not in text:
    raise SystemExit("vb raw pool anchor not found")
text = text.replace(vb_raw_anchor, vb_raw_repl, 1)

pipe_bypass = "        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;\n"
pipe_bypass_repl = pipe_bypass + (
    "#ifdef DTOF_FORCE_RAW10_NONE\n"
    "        vi_cfg->pipe_info[0].pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10;\n"
    "        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;\n"
    "        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
    "#endif\n"
)
count = text.count(pipe_bypass)
if count != 2:
    raise SystemExit(f"expected two dtof bypass anchors, found {count}")
text = text.replace(pipe_bypass, pipe_bypass_repl)

marker = "static volatile sig_atomic_t g_sig_flag = 0;\n"
if marker not in text:
    raise SystemExit("sample marker not found")
text = text.replace(
    marker,
    marker + "\nstatic const char *g_dtof_raw10_create_marker = \"DTOF_RAW10_CREATE_CLEAN\";\n",
    1,
)

print_anchor = "static td_void sample_get_char(td_void)\n"
if print_anchor not in text:
    raise SystemExit("sample_get_char anchor not found")
text = text.replace(
    print_anchor,
    "static td_void sample_dtof_print_raw10_create_marker(td_void)\n"
    "{\n"
    "#ifdef DTOF_RAW10_CREATE_CLEAN\n"
    "    sample_print(\"%s\\n\", g_dtof_raw10_create_marker);\n"
    "#endif\n"
    "}\n\n"
    + print_anchor,
    1,
)

start_anchor = "    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[0], sensor_num);\n"
if start_anchor not in text:
    raise SystemExit("one-dtof start anchor not found")
text = text.replace(
    start_anchor,
    "    sample_dtof_print_raw10_create_marker();\n" + start_anchor,
    1,
)

sample.write_text(text, encoding="utf-8")

common = Path("src/common/sample_comm_vi.c")
common_text = common.read_text(encoding="utf-8", errors="replace")
sony_raw10 = (
    "        if (sns_type == SONY_IMX485_MIPI_8M_30FPS_10BIT_WDR3TO1) {\n"
    "            pipe_info[i].pipe_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;\n"
    "            pipe_info[i].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
    "        }\n"
)
gs1860_raw10 = sony_raw10 + (
    "\n"
    "#ifdef DTOF_FORCE_RAW10_NONE\n"
    "        if (sns_type == HISI_GS1860_MIPI_1M_30FPS_10BIT) {\n"
    "            pipe_info[i].pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10;\n"
    "            pipe_info[i].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;\n"
    "            pipe_info[i].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
    "        }\n"
    "#endif\n"
)
common_count = common_text.count(sony_raw10)
if common_count != 2:
    raise SystemExit(f"expected two common VI raw10 anchors, found {common_count}")
common_text = common_text.replace(sony_raw10, gs1860_raw10)
common.write_text(common_text, encoding="utf-8")

dump = Path("src/dtof/dtof_dumpraw.c")
dump_text = dump.read_text(encoding="utf-8", errors="replace")
dump_attr_block = (
    "        (td_void)memcpy_s(&pipe_attr, sizeof(ot_vi_pipe_attr), &backup_pipe_attr[i], sizeof(ot_vi_pipe_attr));\n"
    "        pipe_attr.pixel_format = pixel_format;\n"
    "        pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
    "\n"
    "        ret = ss_mpi_vi_set_pipe_attr(bind_pipe->pipe_id[i], &pipe_attr);\n"
    "        if (ret != TD_SUCCESS) {\n"
    "            printf(\"set vi_pipe %d attr failed!\\n\", bind_pipe->pipe_id[i]);\n"
    "            return ret;\n"
    "        }\n"
)
dump_keepattr_block = "#ifndef DTOF_KEEP_PIPE_ATTR\n" + dump_attr_block + "#endif\n"
if "#ifndef DTOF_KEEP_PIPE_ATTR" not in dump_text:
    dump_count = dump_text.count(dump_attr_block)
    if dump_count != 1:
        raise SystemExit(f"expected one dump pipe attr block, found {dump_count}")
    dump_text = dump_text.replace(dump_attr_block, dump_keepattr_block, 1)
    dump.write_text(dump_text, encoding="utf-8")
else:
    dump_count = dump_text.count("#ifndef DTOF_KEEP_PIPE_ATTR")

makefile = Path("src/dtof/Makefile")
mk = makefile.read_text(encoding="utf-8", errors="replace")
if "CFLAGS += $(EXTRA_CFLAGS)" not in mk:
    marker = "MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a\n"
    if marker not in mk:
        raise SystemExit("Makefile marker not found")
    mk = mk.replace(marker, marker + "\nCFLAGS += $(EXTRA_CFLAGS)\n", 1)
    makefile.write_text(mk, encoding="utf-8")
    print("RAW10_CREATE_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("RAW10_CREATE_PATCH EXTRA_CFLAGS hook already present")

print(f"RAW10_CREATE_PATCH dtof_bypass_blocks={count} common_vi_blocks={common_count} dump_keepattr_blocks={dump_count}")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_raw10_create_clean_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_raw10_create_clean_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
grep -a -q DTOF_RAW10_CREATE_CLEAN "$BINARY_NAME"
echo "BUILD_MARKER=DTOF_RAW10_CREATE_CLEAN"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
echo "EXTRA_CFLAGS=$EXTRA"
