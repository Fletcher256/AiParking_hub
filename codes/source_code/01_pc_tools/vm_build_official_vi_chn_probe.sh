#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_vi_chn_probe_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_vi_chn_probe_dbg}"
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

python3 - <<'PY'
from pathlib import Path

path = Path("src/dtof/dtof_dumpraw.c")
text = path.read_text()

helper = r'''
#ifdef DTOF_VI_CHN_PROBE
static td_void dtof_chn_probe_print_frame_info(unsigned int frame_idx, const ot_video_frame_info *frame_info)
{
    if (frame_idx > 12 || frame_info == TD_NULL) {
        return;
    }

    const ot_video_frame *video_frame = &frame_info->video_frame;
    td_ulong size = (td_ulong)video_frame->stride[0] * video_frame->height;
    td_u8 *virt_addr = (td_u8 *)ss_mpi_sys_mmap(video_frame->phys_addr[0], size);
    if (virt_addr == TD_NULL) {
        printf("[DTOF_CHN_FRAME] frame=%u mmap_failed phys0=0x%llx size=%llu\n",
            frame_idx,
            (unsigned long long)video_frame->phys_addr[0],
            (unsigned long long)size);
        fflush(stdout);
        return;
    }

    unsigned int row0_sum = 0;
    unsigned int row1_sum = 0;
    unsigned int row2_sum = 0;
    td_u32 sample_len = video_frame->stride[0] < 32 ? video_frame->stride[0] : 32;
    for (td_u32 i = 0; i < sample_len; i++) {
        row0_sum += virt_addr[i];
        if (video_frame->height > 1) {
            row1_sum += virt_addr[video_frame->stride[0] + i];
        }
        if (video_frame->height > 2) {
            row2_sum += virt_addr[2 * video_frame->stride[0] + i];
        }
    }

    printf("[DTOF_CHN_FRAME] frame=%u w=%u h=%u stride0=%u pixfmt=%d compress=%d "
        "phys0=0x%llx time_ref=%u pts=%llu row_sum32=%u/%u/%u "
        "row1_first16=%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
        frame_idx,
        video_frame->width,
        video_frame->height,
        video_frame->stride[0],
        video_frame->pixel_format,
        video_frame->compress_mode,
        (unsigned long long)video_frame->phys_addr[0],
        video_frame->time_ref,
        (unsigned long long)video_frame->pts,
        row0_sum,
        row1_sum,
        row2_sum,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 0] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 1] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 2] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 3] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 4] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 5] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 6] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 7] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 8] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 9] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 10] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 11] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 12] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 13] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 14] : 0,
        video_frame->height > 1 ? virt_addr[video_frame->stride[0] + 15] : 0);
    fflush(stdout);

    ss_mpi_sys_munmap(virt_addr, size);
}

static td_s32 dtof_vi_chn_probe_prepare(ot_vi_pipe vi_pipe)
{
    const ot_vi_chn vi_chn = 0;
    ot_vi_chn_attr chn_attr = {0};
    td_s32 ret = ss_mpi_vi_get_chn_attr(vi_pipe, vi_chn, &chn_attr);
    if (ret != TD_SUCCESS) {
        printf("[DTOF_CHN_PROBE] get_chn_attr pipe=%d chn=%d ret=0x%x\n", vi_pipe, vi_chn, ret);
        fflush(stdout);
        return ret;
    }

    printf("[DTOF_CHN_PROBE] before pipe=%d chn=%d w=%u h=%u pixfmt=%d compress=%d depth=%u dyn=%d video=%d\n",
        vi_pipe, vi_chn,
        chn_attr.size.width, chn_attr.size.height,
        chn_attr.pixel_format, chn_attr.compress_mode,
        chn_attr.depth, chn_attr.dynamic_range, chn_attr.video_format);
    fflush(stdout);

    if (chn_attr.depth == 0) {
        td_s32 disable_ret = ss_mpi_vi_disable_chn(vi_pipe, vi_chn);
        printf("[DTOF_CHN_PROBE] disable_chn ret=0x%x\n", disable_ret);
        chn_attr.depth = 2;
        ret = ss_mpi_vi_set_chn_attr(vi_pipe, vi_chn, &chn_attr);
        printf("[DTOF_CHN_PROBE] set_chn_attr depth=2 ret=0x%x\n", ret);
        if (ret != TD_SUCCESS) {
            fflush(stdout);
            return ret;
        }
        ret = ss_mpi_vi_enable_chn(vi_pipe, vi_chn);
        printf("[DTOF_CHN_PROBE] enable_chn ret=0x%x\n", ret);
        if (ret != TD_SUCCESS) {
            fflush(stdout);
            return ret;
        }
    }

    ret = ss_mpi_vi_get_chn_attr(vi_pipe, vi_chn, &chn_attr);
    if (ret == TD_SUCCESS) {
        printf("[DTOF_CHN_PROBE] after pipe=%d chn=%d w=%u h=%u pixfmt=%d compress=%d depth=%u dyn=%d video=%d\n",
            vi_pipe, vi_chn,
            chn_attr.size.width, chn_attr.size.height,
            chn_attr.pixel_format, chn_attr.compress_mode,
            chn_attr.depth, chn_attr.dynamic_range, chn_attr.video_format);
    } else {
        printf("[DTOF_CHN_PROBE] get_chn_attr_after ret=0x%x\n", ret);
    }
    fflush(stdout);
    return ret;
}

static td_void *dtof_vi_chn_probe_process(td_void *p)
{
    ot_vi_pipe vi_pipe = *(ot_vi_pipe*)p;
    const ot_vi_chn vi_chn = 0;
    unsigned int frame_idx = 0;

    while (g_exit_flag == 0) {
        ot_video_frame_info frame = {0};
        td_s32 ret = ss_mpi_vi_get_chn_frame(vi_pipe, vi_chn, &frame, 1000);
        if (ret != TD_SUCCESS) {
            printf("[DTOF_CHN_PROBE] get_chn_frame pipe=%d chn=%d frame=%u ret=0x%x\n",
                vi_pipe, vi_chn, frame_idx + 1, ret);
            fflush(stdout);
            usleep(100000);
            continue;
        }

        frame_idx++;
        dtof_chn_probe_print_frame_info(frame_idx, &frame);
        ret = ss_mpi_vi_release_chn_frame(vi_pipe, vi_chn, &frame);
        if (ret != TD_SUCCESS) {
            printf("[DTOF_CHN_PROBE] release_chn_frame pipe=%d chn=%d frame=%u ret=0x%x\n",
                vi_pipe, vi_chn, frame_idx, ret);
            fflush(stdout);
        }

        if (frame_idx >= 30) {
            usleep(100000);
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

new = '''#ifdef DTOF_VI_CHN_PROBE
    (td_void)backup_dump_attr;
    (td_void)backup_pipe_attr;
    ret = dtof_vi_chn_probe_prepare(vi_pipe);
    if (ret != TD_SUCCESS) {
        printf("[DTOF_CHN_PROBE] prepare failed ret=0x%x\\n", ret);
        return ret;
    }

    if (bind_pipe.pipe_num == 1) {
        g_exit_flag = 0;
        ret = pthread_create(&g_thread_pid, 0, dtof_vi_chn_probe_process, (td_void*)&vi_pipe);
        if (ret != TD_SUCCESS) {
            printf("[DTOF_CHN_PROBE] create chn probe thread failed\\n");
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
print("VI_CHN_PROBE_PATCH inserted")
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
    print("VI_CHN_PROBE_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("VI_CHN_PROBE_PATCH EXTRA_CFLAGS hook already present")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_vi_chn_probe_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="-DDTOF_VI_CHN_PROBE" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_vi_chn_probe_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
