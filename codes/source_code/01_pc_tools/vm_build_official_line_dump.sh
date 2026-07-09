#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_line_dump_debug_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_line_dump_dbg}"
LINE_DUMP_FRAMES="${LINE_DUMP_FRAMES:-4}"
DUMP_SOURCE="${DUMP_SOURCE:-0}"
export BUILD ZIP LINE_DUMP_FRAMES DUMP_SOURCE

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
import os
from pathlib import Path

src = Path("/tmp/dtof_dumpraw_keepattr_compressparam.c")
if not src.exists():
    raise SystemExit(f"missing source template: {src}")

text = src.read_text()

helper = r'''
static td_void dtof_save_line_dump_frame(ot_vi_pipe vi_pipe, unsigned int frame_idx,
    const ot_video_frame_info *frame_info)
{
    if (frame_idx > DTOF_LINE_DUMP_FRAMES) {
        return;
    }

    const ot_video_frame *video_frame = &frame_info->video_frame;
    td_ulong size = video_frame->stride[0] * video_frame->height;
    td_u8 *virt_addr = (td_u8 *)ss_mpi_sys_mmap(video_frame->phys_addr[0], size);
    if (virt_addr == TD_NULL) {
        printf("[DTOF_LINE_DUMP] frame=%u mmap_failed size=%lu\n", frame_idx, size);
        fflush(stdout);
        return;
    }

    td_char bin_name[128] = {0};
    td_char meta_name[128] = {0};
    snprintf_s(bin_name, sizeof(bin_name), sizeof(bin_name) - 1,
        "dtof_line_dump_f%03u.bin", frame_idx);
    snprintf_s(meta_name, sizeof(meta_name), sizeof(meta_name) - 1,
        "dtof_line_dump_f%03u.meta", frame_idx);

    FILE *bin_fp = fopen(bin_name, "wb");
    if (bin_fp != TD_NULL) {
        fwrite(virt_addr, 1, size, bin_fp);
        fclose(bin_fp);
    }

    FILE *meta_fp = fopen(meta_name, "w");
    if (meta_fp != TD_NULL) {
        ot_vi_compress_param compress_param = {0};
        td_s32 cp_ret = ss_mpi_vi_get_pipe_compress_param(vi_pipe, &compress_param);
        fprintf(meta_fp,
            "frame=%u\nwidth=%u\nheight=%u\nstride0=%u\npixel_format=%d\ncompress_mode=%d\n"
            "phys0=0x%llx\ntime_ref=%llu\npts=%llu\nsize=%lu\n",
            frame_idx,
            video_frame->width,
            video_frame->height,
            video_frame->stride[0],
            video_frame->pixel_format,
            video_frame->compress_mode,
            (unsigned long long)video_frame->phys_addr[0],
            (unsigned long long)video_frame->time_ref,
            (unsigned long long)video_frame->pts,
            size);
        fprintf(meta_fp, "compress_param_ret=0x%x\ncompress_param_size=%u\ncompress_param_hex=",
            cp_ret, OT_VI_COMPRESS_PARAM_SIZE);
        for (td_u32 i = 0; i < OT_VI_COMPRESS_PARAM_SIZE; i++) {
            fprintf(meta_fp, "%02x%s", compress_param.compress_param[i],
                i + 1 == OT_VI_COMPRESS_PARAM_SIZE ? "" : " ");
        }
        fprintf(meta_fp, "\n");
        fclose(meta_fp);
    }

    printf("[DTOF_LINE_DUMP] frame=%u bin=%s meta=%s size=%lu w=%u h=%u stride0=%u pixfmt=%d compress=%d\n",
        frame_idx,
        bin_fp == TD_NULL ? "OPEN_FAILED" : bin_name,
        meta_fp == TD_NULL ? "OPEN_FAILED" : meta_name,
        size,
        video_frame->width,
        video_frame->height,
        video_frame->stride[0],
        video_frame->pixel_format,
        video_frame->compress_mode);
    fflush(stdout);

    ss_mpi_sys_munmap(virt_addr, size);
}
'''

anchor = "static td_void *dump_process(td_void *p)\n"
if anchor not in text:
    raise SystemExit("dump_process anchor not found")
text = text.replace(anchor, helper + "\n" + anchor, 1)

call_anchor = "        dtof_debug_print_frame_info(frame_idx + 1, &astFrame);\n        dtof_debug_print_compress_param(vi_pipe, frame_idx + 1, &astFrame);\n"
call_repl = call_anchor + "        dtof_save_line_dump_frame(vi_pipe, frame_idx + 1, &astFrame);\n"
if call_anchor not in text:
    raise SystemExit("frame debug call anchor not found")
text = text.replace(call_anchor, call_repl, 1)

Path("src/dtof/dtof_dumpraw.c").write_text(text)
print("LINE_DUMP_PATCH inserted frame dump helper")
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
    print("LINE_DUMP_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("LINE_DUMP_PATCH EXTRA_CFLAGS hook already present")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_line_dump_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="-DDTOF_KEEP_PIPE_ATTR -DDTOF_DUMP_SOURCE=${DUMP_SOURCE} -DDTOF_LINE_DUMP_FRAMES=${LINE_DUMP_FRAMES}" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_line_dump_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
echo "DUMP_SOURCE=$DUMP_SOURCE"
