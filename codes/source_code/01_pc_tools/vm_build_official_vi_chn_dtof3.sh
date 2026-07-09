#!/usr/bin/env bash
set -euo pipefail

# v3: nail down the live-VI-chn0 -> DtofProcess path.
# Findings so far:
#   - get_chn_frame on the BYPASS_BE dtof pipe delivers the DECOMPRESSED full
#     histogram (raw_max 1023). This is the data DtofProcess needs.
#   - release_chn_frame returns 0xa0108007 (ILLEGAL_PARAM); release_pipe_frame
#     returns 0x0. v2b used pipe-release: no leak, steady 300 pkts, but frames
#     looked nearly frozen (suspected stale re-serve from wrong queue).
#   - v1 (chn-release fail, leaked) gave live varying frames but stalled at the
#     VB pool size.
# v3 goal: set chn depth at CONFIG time (so the chn has a real user queue from a
# clean lifecycle, no runtime disable/enable), then read with matched
# get/release_chn_frame, and log frame pts/time_ref to prove liveness.

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_vi_chn_dtof3_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_vi_chn_dtof3_dbg}"
FORCE_500PS="${FORCE_500PS:-0}"
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

# ---- patch sample_dtof.c: set ONLY chn0 depth for the dtof pipe (keep YUV420) ----
python3 - <<'PY'
from pathlib import Path

path = Path("src/dtof/sample_dtof.c")
text = path.read_text()

anchor = "        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;\n"
inject = anchor + (
    "#ifdef DTOF_VI_CHN_DTOF\n"
    "        vi_cfg->pipe_info[0].chn_info[0].chn_attr.depth = 4;\n"
    "#endif\n"
)
cnt = text.count(anchor)
if cnt < 2:
    raise SystemExit(f"sample_dtof.c bypass anchor count={cnt} (<2)")
text = text.replace(anchor, inject)
path.write_text(text)
print(f"VI_CHN_DTOF3 sample_dtof.c chn-depth-only injected x{cnt}")
PY

# ---- patch dtof_dumpraw.c: chn read loop feeding DtofProcess + UDP, with pts log ----
python3 - <<'PY'
from pathlib import Path

path = Path("src/dtof/dtof_dumpraw.c")
text = path.read_text()

helper = r'''
#ifdef DTOF_VI_CHN_DTOF
static td_void dtof_chn_dtof_print_frame(unsigned int frame_idx, const DtofHandle *handle, td_u16 *raw_data)
{
    td_u16 raw_min = 0xffff;
    td_u16 raw_max = 0;
    td_u32 raw_nonzero = 0;
    td_u16 out_min = 0xffff;
    td_u16 out_max = 0;
    td_u32 out_nonzero = 0;
    td_u32 out_eq_2 = 0;
    td_u32 i;

    if (frame_idx > 12 || handle == TD_NULL || raw_data == TD_NULL ||
        handle->dtofOutput.distance == TD_NULL) {
        return;
    }

    for (i = 0; i < HEIGHT * WEIGHT * BIN_NUM; i++) {
        td_u16 value = raw_data[i];
        if (value < raw_min) {
            raw_min = value;
        }
        if (value > raw_max) {
            raw_max = value;
        }
        if (value != 0) {
            raw_nonzero++;
        }
    }

    for (i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
        td_u16 value = handle->dtofOutput.distance[i];
        if (value < out_min) {
            out_min = value;
        }
        if (value > out_max) {
            out_max = value;
        }
        if (value != 0) {
            out_nonzero++;
        }
        if (value == 2) {
            out_eq_2++;
        }
    }

    printf("[DTOF_DBG] frame=%u raw_min=%u raw_max=%u raw_nonzero=%u "
        "out_min=%u out_max=%u out_nonzero=%u out_eq_2=%u out_mid=%u "
        "switch=%d config=%d temp=%.2f\n",
        frame_idx, raw_min, raw_max, raw_nonzero,
        out_min, out_max, out_nonzero, out_eq_2,
        handle->dtofOutput.distance[MID_PIXEL],
        handle->dtofOutput.switchFlag, handle->dtofOutput.configFlag,
        handle->temperature);
    fflush(stdout);
}

static td_s32 dtof_vi_chn_dtof_prepare(ot_vi_pipe vi_pipe)
{
    const ot_vi_chn vi_chn = 0;
    ot_vi_chn_attr chn_attr;
    (td_void)memset_s(&chn_attr, sizeof(chn_attr), 0, sizeof(chn_attr));
    td_s32 ret = ss_mpi_vi_get_chn_attr(vi_pipe, vi_chn, &chn_attr);
    if (ret != TD_SUCCESS) {
        printf("[DTOF_CHN_DTOF] get_chn_attr pipe=%d chn=%d ret=0x%x\n", vi_pipe, vi_chn, ret);
        fflush(stdout);
        return ret;
    }

    printf("[DTOF_CHN_DTOF] before pipe=%d chn=%d w=%u h=%u pixfmt=%d compress=%d depth=%u\n",
        vi_pipe, vi_chn, chn_attr.size.width, chn_attr.size.height,
        chn_attr.pixel_format, chn_attr.compress_mode, chn_attr.depth);
    fflush(stdout);

    if (chn_attr.depth == 0) {
        (td_void)ss_mpi_vi_disable_chn(vi_pipe, vi_chn);
        chn_attr.depth = 4;
        ret = ss_mpi_vi_set_chn_attr(vi_pipe, vi_chn, &chn_attr);
        printf("[DTOF_CHN_DTOF] fallback set_chn_attr depth=4 ret=0x%x\n", ret);
        if (ret != TD_SUCCESS) {
            fflush(stdout);
            return ret;
        }
        ret = ss_mpi_vi_enable_chn(vi_pipe, vi_chn);
        printf("[DTOF_CHN_DTOF] fallback enable_chn ret=0x%x\n", ret);
        fflush(stdout);
        return ret;
    }

    printf("[DTOF_CHN_DTOF] using config-time chn depth=%u (clean lifecycle)\n", chn_attr.depth);
    fflush(stdout);
    return TD_SUCCESS;
}

static td_void *dtof_vi_chn_dtof_process(td_void *p)
{
    ot_vi_pipe vi_pipe = *(ot_vi_pipe*)p;
    const ot_vi_chn vi_chn = 0;
    DtofHandle* handle = g_handle;
    unsigned int frame_idx = 0;
    unsigned int count = 0;
    td_u16 switch_flag = 0;
    unsigned int rel_chn_ok = 0;
    unsigned int rel_chn_err = 0;
    unsigned int rel_pipe_ok = 0;
    unsigned int get_idx = 0;

    while (g_exit_flag == 0) {
        ot_video_frame_info frame;
        (td_void)memset_s(&frame, sizeof(frame), 0, sizeof(frame));
        td_s32 ret = ss_mpi_vi_get_chn_frame(vi_pipe, vi_chn, &frame, MILLI_SEC);
        if (ret != TD_SUCCESS) {
            printf("[DTOF_CHN_DTOF] get_chn_frame err pipe=%d ret=0x%x rel_chn_ok=%u rel_chn_err=%u rel_pipe_ok=%u\n",
                vi_pipe, ret, rel_chn_ok, rel_chn_err, rel_pipe_ok);
            fflush(stdout);
            continue;
        }

        get_idx++;
        if (get_idx <= 6) {
            printf("[DTOF_CHN_FRAME] get=%u pixfmt=%d compress=%d stride0=%u time_ref=%u pts=%llu\n",
                get_idx, frame.video_frame.pixel_format, frame.video_frame.compress_mode,
                frame.video_frame.stride[0], frame.video_frame.time_ref,
                (unsigned long long)frame.video_frame.pts);
            fflush(stdout);
        }

        handle->data = deal_frame_data(&frame);
        td_s32 rel = ss_mpi_vi_release_chn_frame(vi_pipe, vi_chn, &frame);
        if (rel == TD_SUCCESS) {
            rel_chn_ok++;
        } else {
            rel_chn_err++;
            td_s32 rel_pipe = ss_mpi_vi_release_pipe_frame(vi_pipe, &frame);
            if (rel_pipe == TD_SUCCESS) {
                rel_pipe_ok++;
            }
            if (get_idx <= 3) {
                printf("[DTOF_CHN_DTOF] chn_rel=0x%x pipe_rel=0x%x\n", rel, rel_pipe);
                fflush(stdout);
            }
        }
        if (handle->data == NULL) {
            printf("[DTOF_CHN_DTOF] deal_frame_data NULL\n");
            fflush(stdout);
            continue;
        }

        handle->dataLen = HEIGHT * WEIGHT * BIN_NUM;
        if (count < 30) {
            ++count;
        } else {
            handle->temperature = gs1860_tsensor_temperature(vi_pipe);
            count = 0;
        }

        if (switch_flag != 0) {
            free(handle->data);
            handle->data = NULL;
            switch_flag--;
            continue;
        }

        DtofProcess(handle);
        frame_idx++;
        dtof_chn_dtof_print_frame(frame_idx, handle, handle->data);
        if (frame_idx == 12) {
            printf("[DTOF_CHN_DTOF] release stats @12: rel_chn_ok=%u rel_chn_err=%u rel_pipe_ok=%u\n",
                rel_chn_ok, rel_chn_err, rel_pipe_ok);
            fflush(stdout);
        }
        free(handle->data);
        handle->data = NULL;
        UdpSendTofData(handle->dtofOutput.distance, handle->dtofOutput.para);

        if (handle->dtofOutput.switchFlag == 1 && handle->dtofOutput.configFlag == 0) {
            printf("------switch to 1000ps-------\n");
            gs1860_1000ps_config(vi_pipe);
            handle->dtofOutput.switchFlag = 0;
            switch_flag = VALID_DATA_NUM;
        } else if (handle->dtofOutput.switchFlag == 1 && handle->dtofOutput.configFlag == 1) {
            printf("------switch to 500ps------\n");
            gs1860_500ps_config(vi_pipe);
            handle->dtofOutput.switchFlag = 0;
            switch_flag = VALID_DATA_NUM;
        }
    }

    return TD_NULL;
}
#endif
'''

anchor = "td_s32 vi_bayerdump(ot_vi_pipe vi_pipe, td_s32 vi_dev)\n"
if anchor not in text:
    raise SystemExit("vi_bayerdump anchor not found")
text = text.replace(anchor, helper + "\n" + anchor, 1)

old = '''    ret = set_dump_pipe_attr(&bind_pipe, backup_dump_attr, OT_VI_MAX_PIPE_NUM, backup_pipe_attr, OT_VI_MAX_PIPE_NUM);
    if (ret != TD_SUCCESS) {
        printf("get_dump_pipe failed 0x%d!\\n", ret);
        return OT_ERR_VI_ILLEGAL_PARAM;
    }

    if (bind_pipe.pipe_num == 1) {
        g_exit_flag = 0;
        ret = pthread_create(&g_thread_pid, 0, dump_process, (td_void*)&vi_pipe);
        if (ret != TD_SUCCESS) {
            printf("dump linear bayer failed\\n");
            return ret;
        }
    }
'''

new = '''#ifdef DTOF_VI_CHN_DTOF
    (td_void)backup_dump_attr;
    (td_void)backup_pipe_attr;
    ret = dtof_vi_chn_dtof_prepare(vi_pipe);
    if (ret != TD_SUCCESS) {
        printf("[DTOF_CHN_DTOF] prepare failed ret=0x%x\\n", ret);
        return ret;
    }

    if (bind_pipe.pipe_num == 1) {
        g_exit_flag = 0;
        ret = pthread_create(&g_thread_pid, 0, dtof_vi_chn_dtof_process, (td_void*)&vi_pipe);
        if (ret != TD_SUCCESS) {
            printf("[DTOF_CHN_DTOF] create chn dtof thread failed\\n");
            return ret;
        }
    }
#else
    ret = set_dump_pipe_attr(&bind_pipe, backup_dump_attr, OT_VI_MAX_PIPE_NUM, backup_pipe_attr, OT_VI_MAX_PIPE_NUM);
    if (ret != TD_SUCCESS) {
        printf("get_dump_pipe failed 0x%d!\\n", ret);
        return OT_ERR_VI_ILLEGAL_PARAM;
    }

    if (bind_pipe.pipe_num == 1) {
        g_exit_flag = 0;
        ret = pthread_create(&g_thread_pid, 0, dump_process, (td_void*)&vi_pipe);
        if (ret != TD_SUCCESS) {
            printf("dump linear bayer failed\\n");
            return ret;
        }
    }
#endif
'''

if old not in text:
    raise SystemExit("vi_bayerdump body anchor not found")
text = text.replace(old, new, 1)

path.write_text(text)
print("VI_CHN_DTOF3 dtof_dumpraw.c patch inserted")
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
    print("VI_CHN_DTOF3 EXTRA_CFLAGS hook inserted")
else:
    print("VI_CHN_DTOF3 EXTRA_CFLAGS hook already present")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_vi_chn_dtof3_clean.log 2>&1 || true
EXTRA_CFLAGS_VALUE="-DDTOF_VI_CHN_DTOF"
if [[ "$FORCE_500PS" == "1" ]]; then
  EXTRA_CFLAGS_VALUE="$EXTRA_CFLAGS_VALUE -DDTOF_FORCE_500PS_CONFIG"
fi
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA_CFLAGS_VALUE" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_vi_chn_dtof3_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
