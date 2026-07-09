#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/os08a20_dtof_build_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
OPEN="${OPEN:-/home/ebaina/Workspace/open_camera-master}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EXTRA="${EXTRA_CFLAGS:--DSUPPORT_RGB=0 -DSUPPORT_DTOF=1 -DDTOF_SKIP_ISP_FOR_PIPE_NO_RUN}"

mkdir -p "$BUILD"
cd "$BUILD"

python3 - <<'PY'
import os
import zipfile
from pathlib import Path

build = Path(os.environ.get("BUILD", ".")).resolve()
zip_path = Path(os.environ.get("ZIP", "/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip"))

with zipfile.ZipFile(zip_path) as zf:
    for member in zf.infolist():
        name = member.filename.replace("\\", "/")
        if not name:
            continue
        target = build / name
        if member.is_dir() or name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, target.open("wb") as dst:
            dst.write(src.read())
PY

TARGET="$BUILD/src/os08a20_dtof"
IMX="$OPEN/mipi_rgb_dtof/code/mipi_imx347"
mkdir -p "$TARGET"
cp -a "$IMX/scene_auto" "$TARGET/"
cp -a "$IMX/dtof" "$TARGET/"
cp "$IMX/dtof_dumpraw.c" "$TARGET/"
cp /tmp/os08a20_dtof.c "$TARGET/os08a20_dtof.c"
cp /tmp/os08a20_dtof.Makefile "$TARGET/Makefile"

python3 - <<'PY'
from pathlib import Path

common = Path("src/common/sample_comm_vi.c")
text = common.read_text(encoding="utf-8", errors="replace")

start_anchor = (
    "        if ((vi_cfg->grp_info.fusion_grp_attr[0].wdr_mode != OT_WDR_MODE_NONE) &&\n"
    "            (vi_cfg->grp_info.fusion_grp_attr[0].wdr_mode != OT_WDR_MODE_BUILT_IN) &&\n"
    "            (i > 0)) {\n"
    "            continue;\n"
    "        }\n"
    "        ret = sample_comm_vi_start_one_pipe_isp(vi_pipe, i, vi_cfg);\n"
)
start_repl = (
    "        if ((vi_cfg->grp_info.fusion_grp_attr[0].wdr_mode != OT_WDR_MODE_NONE) &&\n"
    "            (vi_cfg->grp_info.fusion_grp_attr[0].wdr_mode != OT_WDR_MODE_BUILT_IN) &&\n"
    "            (i > 0)) {\n"
    "            continue;\n"
    "        }\n"
    "#ifdef DTOF_SKIP_ISP_FOR_PIPE_NO_RUN\n"
    "        if (vi_cfg->pipe_info[i].isp_need_run != TD_TRUE) {\n"
    "            continue;\n"
    "        }\n"
    "#endif\n"
    "        ret = sample_comm_vi_start_one_pipe_isp(vi_pipe, i, vi_cfg);\n"
)
if start_anchor not in text:
    raise SystemExit("sample_comm_vi_start_isp anchor not found")
text = text.replace(start_anchor, start_repl, 1)

stop_anchor = (
    "        vi_pipe = vi_cfg->bind_pipe.pipe_id[i];\n"
    "        sample_comm_vi_stop_one_pipe_isp(vi_pipe);\n"
)
stop_repl = (
    "        vi_pipe = vi_cfg->bind_pipe.pipe_id[i];\n"
    "#ifdef DTOF_SKIP_ISP_FOR_PIPE_NO_RUN\n"
    "        if (g_start_isp[vi_pipe] != TD_TRUE) {\n"
    "            continue;\n"
    "        }\n"
    "#endif\n"
    "        sample_comm_vi_stop_one_pipe_isp(vi_pipe);\n"
)
if stop_anchor not in text:
    raise SystemExit("sample_comm_vi_stop_isp anchor not found")
text = text.replace(stop_anchor, stop_repl, 1)

common.write_text(text, encoding="utf-8")
print("OS08_DTOF_PATCH common VI skips ISP when pipe_info[].isp_need_run is false")
PY

cd "$TARGET"
env PATH="$TOOLCHAIN" make OS_TYPE=linux EXTRA_CFLAGS="$EXTRA" -j4 2>&1 | tee /tmp/os08a20_dtof_build.log
cp sample_os08a20_dtof sample_os08a20_dtof_dtofonly

sha256sum sample_os08a20_dtof_dtofonly
file sample_os08a20_dtof_dtofonly
readelf -l sample_os08a20_dtof_dtofonly | grep "Requesting program interpreter" || true
strings sample_os08a20_dtof_dtofonly | grep -E "starting OS08A20|dtof|Usage|vi_bayerdump|distance" | head -40 || true
echo "BUILD_DIR=$BUILD"
echo "BINARY=$TARGET/sample_os08a20_dtof_dtofonly"
echo "EXTRA_CFLAGS=$EXTRA"
