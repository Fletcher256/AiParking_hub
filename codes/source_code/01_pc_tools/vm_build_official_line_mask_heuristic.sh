#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_line_mask_heuristic_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_line_mask4095_v2_dbg}"
EXTRA_CFLAGS="${EXTRA_CFLAGS:--DDTOF_KEEP_PIPE_ATTR -DDTOF_DUMP_SOURCE=0 -DDTOF_LINE_MASK_HEURISTIC -DDTOF_LINE_MASK_AMPLITUDE=4095}"
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

cp /tmp/official_sample_dtof_keepattr_debug.c "$BUILD/src/dtof/sample_dtof.c"
cp /tmp/official_dtof_dumpraw_keepattr_debug.c "$BUILD/src/dtof/dtof_dumpraw.c"

python3 - <<'PY'
from pathlib import Path

dump = Path("src/dtof/dtof_dumpraw.c")
text = dump.read_text()

helper_marker = "static td_u16* deal_frame_data(ot_video_frame_info *frame_info)\n"
helper = r'''
#ifndef DTOF_LINE_MASK_HEURISTIC
#define DTOF_LINE_MASK_HEURISTIC
#endif

#ifndef DTOF_LINE_MASK_AMPLITUDE
#define DTOF_LINE_MASK_AMPLITUDE 4095
#endif

static td_s32 dtof_one_zero_bit_index(td_u32 word)
{
    td_u32 diff = ~word;
    if (diff == 0 || (diff & (diff - 1)) != 0) {
        return -1;
    }

    for (td_s32 bit = 0; bit < 32; bit++) {
        if ((diff & (1U << bit)) != 0) {
            return bit;
        }
    }
    return -1;
}

static td_bool dtof_try_decode_line_mask(const ot_video_frame *video_frame, const td_u8 *base, td_u16 *out)
{
    static td_u32 print_count = 0;
    const td_u32 header_bytes = 16; /* four non-mask words seen before the 40x64 mask segment */
    const td_u32 mask_words = WEIGHT * (BIN_NUM / 32);
    td_u32 active_bins = 0;
    td_u32 decoded_rows = 0;

    if (video_frame == TD_NULL || base == TD_NULL || out == TD_NULL) {
        return TD_FALSE;
    }
    if (video_frame->compress_mode != OT_COMPRESS_MODE_LINE ||
        video_frame->pixel_format != OT_PIXEL_FORMAT_RGB_BAYER_12BPP ||
        video_frame->width != WEIGHT * BIN_NUM ||
        video_frame->height < HEIGHT + 1 ||
        video_frame->stride[0] < header_bytes + mask_words * sizeof(td_u32)) {
        return TD_FALSE;
    }

    (td_void)memset_s(out, 2 * video_frame->width * video_frame->height,
        0, 2 * video_frame->width * video_frame->height);

    for (td_u32 row = 0; row < HEIGHT; row++) {
        const td_u8 *row_ptr = base + (row + 1) * video_frame->stride[0] + header_bytes;
        td_u32 row_active = 0;

        for (td_u32 col = 0; col < WEIGHT; col++) {
            for (td_u32 half = 0; half < 2; half++) {
                td_u32 word = 0;
                td_s32 bit;
                td_u32 word_idx = col * 2 + half;
                (td_void)memcpy_s(&word, sizeof(word), row_ptr + word_idx * sizeof(td_u32), sizeof(word));
                bit = dtof_one_zero_bit_index(word);
                if (bit < 0) {
                    continue;
                }
                out[row * WEIGHT * BIN_NUM + col * BIN_NUM + half * 32 + (td_u32)bit] =
                    (td_u16)DTOF_LINE_MASK_AMPLITUDE;
                row_active++;
            }
        }

        if (row_active != 0) {
            decoded_rows++;
            active_bins += row_active;
        }
    }

    if (print_count < 12) {
        printf("[DTOF_MASK] frame_hint=%u decoded_rows=%u active_bins=%u amplitude=%u "
            "pixfmt=%d compress=%d stride0=%u\n",
            print_count + 1,
            decoded_rows,
            active_bins,
            (td_u32)DTOF_LINE_MASK_AMPLITUDE,
            video_frame->pixel_format,
            video_frame->compress_mode,
            video_frame->stride[0]);
        fflush(stdout);
        print_count++;
    }

    return decoded_rows == HEIGHT ? TD_TRUE : TD_FALSE;
}

'''
if helper_marker not in text:
    raise SystemExit("deal_frame_data marker not found")
text = text.replace(helper_marker, helper + "\n" + helper_marker, 1)

branch_marker = "    td_s32 s32outcnt = 0;\n"
branch = r'''#ifdef DTOF_LINE_MASK_HEURISTIC
    if (dtof_try_decode_line_mask(video_frame, virt_addr, pu16data) == TD_TRUE) {
        ss_mpi_sys_munmap(virt_addr, size);
        virt_addr = TD_NULL;
        return pu16data;
    }
#endif

'''
if branch_marker not in text:
    raise SystemExit("deal_frame_data branch marker not found")
text = text.replace(branch_marker, branch + branch_marker, 1)
dump.write_text(text)

print("LINE_MASK_HEURISTIC_PATCH applied")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_line_mask_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA_CFLAGS" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_line_mask_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
