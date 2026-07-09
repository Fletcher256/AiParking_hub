#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
SRC="${SRC:-/home/ebaina/Workspace/open_camera-master}"
BUILD="${BUILD:-/home/ebaina/open_camera_dtof_auto_${timestamp}}"
SDK_MPP="${SDK_MPP:-/home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp}"
SDK_SAMPLE="${SDK_SAMPLE:-$SDK_MPP/sample}"
SDK_PARAM="${SDK_PARAM:-/home/ebaina/official_dtof_raw10_create_clean_20260602_202802/src/Makefile.param}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

test -d "$SRC/mipi_rgb_dtof/code/mipi_imx347"
test -f "$SDK_PARAM"
test -f "$SDK_SAMPLE/smp_linux.mak"

rm -rf "$BUILD"
mkdir -p "$BUILD"
cp -a "$SRC/." "$BUILD/"
cp "$SDK_SAMPLE/smp_linux.mak" "$BUILD/mipi_rgb_dtof/code/smp_linux.mak"

export BUILD SDK_PARAM
python3 - <<'PY'
import os
from pathlib import Path

build = Path(os.environ["BUILD"])
sdk_param = Path(os.environ["SDK_PARAM"])
param = build / "mipi_rgb_dtof/code/Makefile.param"
text = param.read_text(encoding="utf-8", errors="replace")
old = (
    "ifeq ($(PARAM_FILE), )\n"
    "     PARAM_FILE := ../../Makefile.param\n"
    "     include $(PARAM_FILE)\n"
    "endif\n"
)
new = (
    f"PARAM_FILE := {sdk_param}\n"
    "include $(PARAM_FILE)\n"
    "SENSOR0_TYPE := SONY_IMX347_SLAVE_MIPI_4M_30FPS_12BIT\n"
    "SENSOR1_TYPE := HISI_GS1860_MIPI_1M_30FPS_10BIT\n"
    "SENSOR2_TYPE := HISI_GS1860_MIPI_1M_30FPS_10BIT\n"
    "SENSOR3_TYPE := OV_OS08A20_MIPI_8M_30FPS_12BIT\n"
    "REL_INC := $(SAMPLE_DIR)/include/hisilicon\n"
    "OT_ARCH := ss928v100\n"
    "OT_FPGA := OT_XXXX\n"
    "COMMON_DIR = $(PWD)/../common\n"
    "AUDIO_ADP_DIR = $(PWD)/../audio/adp\n"
    "AUDIO_LIBA := $(AUDIO_LIBS)\n"
    "MPI_LIBS := ./dtof/lib/libdepth_process.a ./dtof/lib/libsns_gs1860.a $(filter-out %/libsns_gs1860.a,$(MPI_LIBS))\n"
)
if old not in text:
    raise SystemExit("Makefile.param include anchor not found")
text = text.replace(old, new, 1)
mpi_start = text.find("MPI_LIBS := $(REL_LIB)/libss_mpi.a\n")
audio_start = text.find("AUDIO_LIBA := $(REL_LIB)/libss_voice_engine.a\n")
if mpi_start < 0 or audio_start < 0 or audio_start <= mpi_start:
    raise SystemExit("open_camera MPI_LIBS override block not found")
text = text[:mpi_start] + text[audio_start:]
audio_end_marker = "#########################################################################\n"
audio_start = text.find("AUDIO_LIBA := $(REL_LIB)/libss_voice_engine.a\n")
audio_end = text.find(audio_end_marker, audio_start)
if audio_start < 0 or audio_end < 0:
    raise SystemExit("open_camera AUDIO_LIBA block not found")
text = text[:audio_start] + text[audio_end:]
comm_start = text.find("#COMM_SRC := $(wildcard $(COMMON_DIR)/*.c)\n")
media_start = text.find("MEDIA_MSG_CLIENT_SRC :=", comm_start)
if comm_start < 0 or media_start < 0:
    raise SystemExit("open_camera COMM_SRC block not found")
comm_block = (
    "#COMM_SRC := $(wildcard $(COMMON_DIR)/*.c)\n"
    "COMM_SRC := $(wildcard $(COMMON_DIR)/sample_comm_sys.c)\n"
    "COMM_SRC += $(wildcard $(COMMON_DIR)/sample_comm_isp.c)\n"
    "COMM_SRC += $(wildcard $(COMMON_DIR)/sample_comm_vi.c)\n"
    "COMM_OBJ := $(COMM_SRC:%.c=%.o)\n"
    "COMM_INC := -I$(COMMON_DIR)\n"
    "COMM_INC += -I$(AUDIO_ADP_DIR)\n\n"
)
text = text[:comm_start] + comm_block + text[media_start:]
text += (
    "\nCFLAGS += -I$(PWD)/dtof/include\n"
    "CFLAGS += -I$(PWD)/scene_auto/include\n"
    "CFLAGS += -I$(PWD)/scene_auto/src/sample\n"
    "CFLAGS += -I$(PWD)/scene_auto/tools/configaccess/include\n"
    "CFLAGS += -I$(PWD)/scene_auto/tools/iniparser/include\n"
    "CFLAGS += -I$(PWD)/ffmpeg/include\n"
    "CFLAGS += -I$(PWD)/livertsp/include\n"
    "CFLAGS += -Wl,--gc-sections\n"
)
param.write_text(text, encoding="utf-8")

makefile = build / "mipi_rgb_dtof/code/mipi_imx347/Makefile"
mk = makefile.read_text(encoding="utf-8", errors="replace")
mk = mk.replace(
    "SMP_SRCS := $(wildcard $(CURDIR)/*.c)\n"
    "SMP_SRCS += $(wildcard $(CURDIR)/scene_auto/tools/configaccess/src/*.c)\n"
    "SMP_SRCS += $(wildcard $(CURDIR)/scene_auto/tools/iniparser/src/*.c)\n"
    "SMP_SRCS += $(wildcard $(CURDIR)/scene_auto/src/core/*.c)\n"
    "SMP_SRCS += $(CURDIR)/scene_auto/src/sample/scene_loadparam.c\n",
    "SMP_SRCS := $(CURDIR)/dtof_dumpraw.c\n"
    "SMP_SRCS += $(CURDIR)/imx347.c\n"
    "SMP_SRCS += $(CURDIR)/pwm.c\n",
)
mk = mk.replace("MPI_LIBS += ./sensor/lib/libsns_imx347_slave.a\n", "")
mk = mk.replace("MPI_LIBS += ./dtof/lib/libdepth_process.a\n", "")
mk = mk.replace("MPI_LIBS += ./dtof/lib/libsns_gs1860.a\n", "")
makefile.write_text(mk, encoding="utf-8")

src = build / "mipi_rgb_dtof/code/mipi_imx347/imx347.c"
code = src.read_text(encoding="utf-8", errors="replace")
start = code.find("    sigint_handler(sample_vio_handlesig);\n")
if start < 0:
    raise SystemExit("main signal-handler anchor not found")
end_marker = "\treturn 0;\n}\n"
end = code.find(end_marker, start)
if end < 0:
    raise SystemExit("main return anchor not found")
end += len(end_marker)
replacement = (
    "    sigint_handler(sample_vio_handlesig);\n"
    "    printf(\"ROUTE1_DTOF_AUTO_START\\n\");\n"
    "    fflush(stdout);\n"
    "    ret = sample_vio_one_sensor0_and_dtof0(sns_info[sns_num].i2c_bus, server_ip);\n"
    "    return ret;\n"
    "}\n"
)
code = code[:start] + replacement + code[end:]

route_replacements = {
    "    ot_vi_pipe vi_pipe[2] = {0, 2}; /* 2 pipe */\n":
        "    ot_vi_pipe vi_pipe[2] = {0, 1}; /* dToF on official J3 pipe1 */\n",
    """    } else if(i2c_bus == 4) {
        const ot_vi_dev vi_dev = 2; /* dev2 for sensor2 */
        const ot_vi_pipe vi_pipe = 2; /* dev2 bind pipe2(sensor2) */
        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg0);
        vi_cfg0->sns_info.bus_id = 4; /* i2c4 */
        vi_cfg0->sns_info.sns_clk_src = 2;
        vi_cfg0->sns_info.sns_rst_src = 2;

        vi_cfg0->mipi_info.mipi_dev = 2;
        vi_cfg0->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;
        vi_cfg0->mipi_info.combo_dev_attr.devno = 2;
        vi_cfg0->mipi_info.combo_dev_attr.mipi_attr.lane_id[0] = 4;
        vi_cfg0->mipi_info.ext_data_type_attr.devno = 2;
        vi_cfg0->dev_info.vi_dev = vi_dev;
        vi_cfg0->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg0->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
        vi_cfg0->pipe_info[0].isp_need_run = TD_FALSE;
        vi_cfg0->pipe_info[0].chn_need_start = TD_TRUE;
    }
""": """    } else if(i2c_bus == 4) {
        const ot_vi_dev vi_dev = 2; /* dev2 for sensor2/J3 */
        const ot_vi_pipe vi_pipe = 1; /* official dToF sample binds dev2 to pipe1 */
        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg0);
        vi_cfg0->sns_info.bus_id = 4; /* i2c4 */
        vi_cfg0->sns_info.sns_clk_src = 1;
        vi_cfg0->sns_info.sns_rst_src = 1;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg0->mipi_info);
        vi_cfg0->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;
        vi_cfg0->dev_info.vi_dev = vi_dev;
        vi_cfg0->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg0->grp_info.grp_num = 1;
        vi_cfg0->grp_info.fusion_grp[0] = 0;
        vi_cfg0->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
        vi_cfg0->pipe_info[0].isp_need_run = TD_FALSE;
        vi_cfg0->pipe_info[0].chn_need_start = TD_TRUE;
        vi_cfg0->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;
    }
""",
}
for old, new in route_replacements.items():
    if old not in code:
        raise SystemExit("expected open_camera dToF route anchor not found")
    code = code.replace(old, new, 1)
src.write_text(code, encoding="utf-8")

isp = build / "mipi_rgb_dtof/code/common/sample_comm_isp.c"
isp_text = isp.read_text(encoding="utf-8", errors="replace")
extern_anchor = "extern ot_isp_sns_obj g_sns_os04a10_obj;\n"
extern_extra = (
    "extern ot_isp_sns_obj g_sns_os04a10_obj;\n"
    "extern ot_isp_sns_obj g_sns_os08b10_obj;\n"
    "extern ot_isp_sns_obj g_sns_imx347_2l_slave_obj;\n"
    "extern ot_isp_sns_obj g_sns_sc450ai_obj;\n"
    "extern ot_isp_sns_obj g_sns_sc450ai_2l_obj;\n"
    "extern ot_isp_sns_obj g_sns_imx219_2l_obj;\n"
    "extern ot_isp_sns_obj g_sns_gs1860_obj;\n"
)
if "g_sns_gs1860_obj" not in isp_text.split("td_s32 sample_comm_isp_get_pub_attr_by_sns", 1)[0]:
    if extern_anchor not in isp_text:
        raise SystemExit("sample_comm_isp extern anchor not found")
    isp_text = isp_text.replace(extern_anchor, extern_extra, 1)
    isp.write_text(isp_text, encoding="utf-8")
PY

cd "$BUILD/mipi_rgb_dtof/code/mipi_imx347"
env PATH="$TOOLCHAIN" make clean ARM_ARCH=smp OSTYPE=linux >/tmp/open_camera_dtof_auto_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make ARM_ARCH=smp OSTYPE=linux all 2>&1 | tee /tmp/open_camera_dtof_auto_build.log >/dev/null
cp sample_vio sample_vio_dtof_auto
grep -a -q ROUTE1_DTOF_AUTO_START sample_vio_dtof_auto
sha256sum sample_vio_dtof_auto
ls -l sample_vio_dtof_auto
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/mipi_rgb_dtof/code/mipi_imx347/sample_vio_dtof_auto"
