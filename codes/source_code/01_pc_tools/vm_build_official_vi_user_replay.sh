#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_vi_user_replay_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
EEPROM_BIN="${EEPROM_BIN:-/home/ebaina/gs1860_eeprom_521.bin}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_vi_user_replay_dbg}"
EXTRA_CFLAGS="${EXTRA_CFLAGS:--DDTOF_VI_USER_REPLAY}"
export BUILD ZIP EEPROM_BIN

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
import os

eeprom = Path(os.environ["EEPROM_BIN"]).read_bytes()
if len(eeprom) != 521:
    raise SystemExit(f"expected 521-byte EEPROM, got {len(eeprom)} from {os.environ['EEPROM_BIN']}")
eeprom_array = ", ".join(f"0x{byte:02x}" for byte in eeprom)

dump = Path("src/dtof/dtof_dumpraw.c")
text = dump.read_text()
helper_marker = "td_s32 dtof_init(ot_vi_pipe vi_pipe, td_char* serverip)\n"
helper_template = r'''
#ifdef DTOF_VI_USER_REPLAY
#include "ot_buffer.h"
#include "ss_mpi_sys.h"
#include "ss_mpi_vb.h"
#include "ss_mpi_vi.h"

#define DTOF_REPLAY_EEPROM_LEN 521
#define DTOF_REPLAY_WIDTH 2560
#define DTOF_REPLAY_HEIGHT 31
#define DTOF_REPLAY_TIMEOUT_MS 1000
#define DTOF_REPLAY_MIN_COMMON_BLK 262144

#ifndef DTOF_REPLAY_USE_DEV_BIND
#define DTOF_REPLAY_USE_DEV_BIND 1
#endif

#ifndef DTOF_REPLAY_DEFAULT_DEV
#define DTOF_REPLAY_DEFAULT_DEV 3
#endif

#ifndef DTOF_REPLAY_PIPE_BYPASS
#define DTOF_REPLAY_PIPE_BYPASS OT_VI_PIPE_BYPASS_BE
#endif

#ifndef DTOF_REPLAY_PIPE_COMPRESS
#define DTOF_REPLAY_PIPE_COMPRESS OT_COMPRESS_MODE_LINE
#endif

#ifndef DTOF_REPLAY_INPUT_COMPRESS
#define DTOF_REPLAY_INPUT_COMPRESS OT_COMPRESS_MODE_LINE
#endif

#ifndef DTOF_REPLAY_START_CHN
#define DTOF_REPLAY_START_CHN 1
#endif

static const td_u8 g_dtof_replay_eeprom[DTOF_REPLAY_EEPROM_LEN] = { __EEPROM_ARRAY__ };

typedef struct {
    ot_vb_pool pool;
    ot_vb_blk blk;
    td_phys_addr_t phys;
    td_void *virt;
    td_u32 size;
    ot_video_frame_info frame;
} dtof_replay_input_frame;

static int dtof_replay_cmp_u16(const void *a, const void *b)
{
    td_u16 va = *(const td_u16 *)a;
    td_u16 vb = *(const td_u16 *)b;
    return (va > vb) - (va < vb);
}

static td_s32 dtof_replay_read_file(const char *path, td_u8 **data, td_u32 *len)
{
    FILE *fp;
    long size;
    size_t got;

    if (path == TD_NULL || data == TD_NULL || len == TD_NULL) {
        return TD_FAILURE;
    }

    fp = fopen(path, "rb");
    if (fp == TD_NULL) {
        printf("[VI_REPLAY_ERROR] open_failed path=%s errno=%d\n", path, errno);
        return TD_FAILURE;
    }
    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return TD_FAILURE;
    }
    size = ftell(fp);
    if (size <= 0 || size > 1024 * 1024) {
        fclose(fp);
        printf("[VI_REPLAY_ERROR] bad_size path=%s size=%ld\n", path, size);
        return TD_FAILURE;
    }
    rewind(fp);

    *data = (td_u8 *)malloc((size_t)size);
    if (*data == TD_NULL) {
        fclose(fp);
        return TD_FAILURE;
    }
    got = fread(*data, 1, (size_t)size, fp);
    fclose(fp);
    if (got != (size_t)size) {
        free(*data);
        *data = TD_NULL;
        return TD_FAILURE;
    }

    *len = (td_u32)size;
    return TD_SUCCESS;
}

static td_u64 dtof_replay_common_block_size(td_u64 raw_blk_size)
{
    return raw_blk_size > DTOF_REPLAY_MIN_COMMON_BLK ? raw_blk_size : DTOF_REPLAY_MIN_COMMON_BLK;
}

static td_s32 dtof_replay_sys_init(td_u64 raw_blk_size)
{
    ot_vb_cfg vb_cfg;
    td_s32 ret;

    memset(&vb_cfg, 0, sizeof(vb_cfg));
    vb_cfg.max_pool_cnt = OT_VB_MAX_COMMON_POOLS;
    vb_cfg.common_pool[0].blk_size = dtof_replay_common_block_size(raw_blk_size);
    vb_cfg.common_pool[0].blk_cnt = 6;
    vb_cfg.common_pool[0].remap_mode = OT_VB_REMAP_MODE_NONE;

    printf("[VI_REPLAY_SYS] common_blk_size=%llu common_blk_cnt=%u\n",
        (unsigned long long)vb_cfg.common_pool[0].blk_size,
        vb_cfg.common_pool[0].blk_cnt);
    ret = sample_comm_sys_init(&vb_cfg);
    printf("[VI_REPLAY_SYS] sample_comm_sys_init_ret=0x%x\n", ret);
    return ret;
}

static td_void dtof_replay_calc_input_buf(ot_vb_calc_cfg *calc_cfg)
{
    ot_pic_buf_attr buf_attr;

    memset(&buf_attr, 0, sizeof(buf_attr));
    buf_attr.width = DTOF_REPLAY_WIDTH;
    buf_attr.height = DTOF_REPLAY_HEIGHT;
    buf_attr.align = OT_DEFAULT_ALIGN;
    buf_attr.bit_width = OT_DATA_BIT_WIDTH_8;
    buf_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    buf_attr.compress_mode = DTOF_REPLAY_INPUT_COMPRESS;
    ot_common_get_pic_buf_cfg(&buf_attr, calc_cfg);
}

static td_s32 dtof_replay_alloc_input_frame(dtof_replay_input_frame *input,
    const td_u8 *raw, td_u32 raw_len, const ot_vb_calc_cfg *calc_cfg)
{
    ot_vb_pool_cfg pool_cfg;

    if (input == TD_NULL || raw == TD_NULL || calc_cfg == TD_NULL) {
        return TD_FAILURE;
    }
    if ((td_u64)raw_len > calc_cfg->vb_size) {
        printf("[VI_REPLAY_ERROR] raw_too_large raw_len=%u vb_size=%llu\n",
            raw_len, (unsigned long long)calc_cfg->vb_size);
        return TD_FAILURE;
    }

    memset(input, 0, sizeof(*input));
    input->pool = OT_VB_INVALID_POOL_ID;
    input->blk = OT_VB_INVALID_HANDLE;

    memset(&pool_cfg, 0, sizeof(pool_cfg));
    pool_cfg.blk_size = calc_cfg->vb_size;
    pool_cfg.blk_cnt = 1;
    pool_cfg.remap_mode = OT_VB_REMAP_MODE_NONE;
    input->pool = ss_mpi_vb_create_pool(&pool_cfg);
    if (input->pool == OT_VB_INVALID_POOL_ID) {
        printf("[VI_REPLAY_ERROR] ss_mpi_vb_create_pool_failed blk_size=%llu\n",
            (unsigned long long)pool_cfg.blk_size);
        return TD_FAILURE;
    }

    input->blk = ss_mpi_vb_get_blk(input->pool, calc_cfg->vb_size, TD_NULL);
    if (input->blk == OT_VB_INVALID_HANDLE) {
        printf("[VI_REPLAY_ERROR] ss_mpi_vb_get_blk_failed\n");
        ss_mpi_vb_destroy_pool(input->pool);
        input->pool = OT_VB_INVALID_POOL_ID;
        return TD_FAILURE;
    }

    input->phys = ss_mpi_vb_handle_to_phys_addr(input->blk);
    input->size = (td_u32)calc_cfg->vb_size;
    input->virt = ss_mpi_sys_mmap(input->phys, input->size);
    if (input->virt == TD_NULL) {
        printf("[VI_REPLAY_ERROR] ss_mpi_sys_mmap_input_failed phys=0x%llx size=%u\n",
            (unsigned long long)input->phys, input->size);
        ss_mpi_vb_release_blk(input->blk);
        ss_mpi_vb_destroy_pool(input->pool);
        input->blk = OT_VB_INVALID_HANDLE;
        input->pool = OT_VB_INVALID_POOL_ID;
        return TD_FAILURE;
    }

    memset(input->virt, 0, input->size);
    memcpy(input->virt, raw, raw_len);

    input->frame.pool_id = input->pool;
    input->frame.mod_id = OT_ID_VI;
    input->frame.video_frame.phys_addr[0] = input->phys;
    input->frame.video_frame.phys_addr[1] = input->phys + calc_cfg->main_y_size;
    input->frame.video_frame.virt_addr[0] = input->virt;
    input->frame.video_frame.virt_addr[1] = (td_u8 *)input->virt + calc_cfg->main_y_size;
    input->frame.video_frame.stride[0] = calc_cfg->main_stride;
    input->frame.video_frame.stride[1] = calc_cfg->main_stride;
    input->frame.video_frame.width = DTOF_REPLAY_WIDTH;
    input->frame.video_frame.height = DTOF_REPLAY_HEIGHT;
    input->frame.video_frame.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    input->frame.video_frame.video_format = OT_VIDEO_FORMAT_LINEAR;
    input->frame.video_frame.compress_mode = DTOF_REPLAY_INPUT_COMPRESS;
    input->frame.video_frame.dynamic_range = OT_DYNAMIC_RANGE_SDR8;
    input->frame.video_frame.field = OT_VIDEO_FIELD_FRAME;
    input->frame.video_frame.color_gamut = OT_COLOR_GAMUT_BT601;

    printf("[VI_REPLAY_INPUT] raw_len=%u vb_size=%llu stride=%u main_y_size=%u pixfmt=%d compress=%d phys=0x%llx\n",
        raw_len,
        (unsigned long long)calc_cfg->vb_size,
        calc_cfg->main_stride,
        calc_cfg->main_y_size,
        input->frame.video_frame.pixel_format,
        input->frame.video_frame.compress_mode,
        (unsigned long long)input->phys);
    return TD_SUCCESS;
}

static td_void dtof_replay_free_input_frame(dtof_replay_input_frame *input)
{
    if (input == TD_NULL) {
        return;
    }
    if (input->virt != TD_NULL && input->size != 0) {
        ss_mpi_sys_munmap(input->virt, input->size);
        input->virt = TD_NULL;
    }
    if (input->blk != OT_VB_INVALID_HANDLE) {
        ss_mpi_vb_release_blk(input->blk);
        input->blk = OT_VB_INVALID_HANDLE;
    }
    if (input->pool != OT_VB_INVALID_POOL_ID) {
        ss_mpi_vb_destroy_pool(input->pool);
        input->pool = OT_VB_INVALID_POOL_ID;
    }
}

static td_s32 dtof_replay_start_dev_bind(ot_vi_dev vi_dev, ot_vi_pipe vi_pipe)
{
    sample_vi_cfg vi_cfg;
    td_s32 ret;

    memset(&vi_cfg, 0, sizeof(vi_cfg));
    sample_comm_vi_get_default_vi_cfg(HISI_GS1860_MIPI_1M_30FPS_10BIT, &vi_cfg);
    vi_cfg.dev_info.vi_dev = vi_dev;

    printf("[VI_REPLAY_DEV] set_attr dev=%d in_w=%u in_h=%u intf=%d work_mode=%d\n",
        vi_dev,
        vi_cfg.dev_info.dev_attr.in_size.width,
        vi_cfg.dev_info.dev_attr.in_size.height,
        vi_cfg.dev_info.dev_attr.intf_mode,
        vi_cfg.dev_info.dev_attr.work_mode);

    ret = ss_mpi_vi_set_dev_attr(vi_dev, &vi_cfg.dev_info.dev_attr);
    printf("[VI_REPLAY_DEV] set_attr_ret=0x%x\n", ret);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    ret = ss_mpi_vi_enable_dev(vi_dev);
    printf("[VI_REPLAY_DEV] enable_ret=0x%x\n", ret);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    ret = ss_mpi_vi_bind(vi_dev, vi_pipe);
    printf("[VI_REPLAY_DEV] bind_ret=0x%x dev=%d pipe=%d\n", ret, vi_dev, vi_pipe);
    if (ret != TD_SUCCESS) {
        ss_mpi_vi_disable_dev(vi_dev);
        return ret;
    }

    return TD_SUCCESS;
}

static td_void dtof_replay_stop_dev_bind(ot_vi_dev vi_dev, ot_vi_pipe vi_pipe)
{
    td_s32 ret;

    ret = ss_mpi_vi_unbind(vi_dev, vi_pipe);
    printf("[VI_REPLAY_DEV] unbind_ret=0x%x dev=%d pipe=%d\n", ret, vi_dev, vi_pipe);
    ret = ss_mpi_vi_disable_dev(vi_dev);
    printf("[VI_REPLAY_DEV] disable_ret=0x%x dev=%d\n", ret, vi_dev);
}

static td_s32 dtof_replay_create_pipe(ot_vi_pipe vi_pipe)
{
    sample_vi_cfg vi_cfg;
    ot_vi_pipe_attr pipe_attr;
    ot_vi_chn_attr chn_attr;
    td_s32 ret;

    memset(&vi_cfg, 0, sizeof(vi_cfg));
    sample_comm_vi_get_default_vi_cfg(HISI_GS1860_MIPI_1M_30FPS_10BIT, &vi_cfg);
    memcpy(&pipe_attr, &vi_cfg.pipe_info[0].pipe_attr, sizeof(pipe_attr));
    pipe_attr.pipe_bypass_mode = DTOF_REPLAY_PIPE_BYPASS;
    pipe_attr.isp_bypass = TD_FALSE;
    pipe_attr.size.width = DTOF_REPLAY_WIDTH;
    pipe_attr.size.height = DTOF_REPLAY_HEIGHT;
    pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    pipe_attr.compress_mode = DTOF_REPLAY_PIPE_COMPRESS;
    pipe_attr.bit_width = OT_DATA_BIT_WIDTH_8;
    pipe_attr.bit_align_mode = OT_VI_BIT_ALIGN_MODE_HIGH;
    pipe_attr.frame_rate_ctrl.src_frame_rate = -1;
    pipe_attr.frame_rate_ctrl.dst_frame_rate = -1;

    printf("[VI_REPLAY_PIPE] create pipe=%d bypass=%d isp_bypass=%d w=%u h=%u pixfmt=%d compress=%d bit_width=%d\n",
        vi_pipe,
        pipe_attr.pipe_bypass_mode,
        pipe_attr.isp_bypass,
        pipe_attr.size.width,
        pipe_attr.size.height,
        pipe_attr.pixel_format,
        pipe_attr.compress_mode,
        pipe_attr.bit_width);

    ret = ss_mpi_vi_create_pipe(vi_pipe, &pipe_attr);
    printf("[VI_REPLAY_PIPE] create_ret=0x%x\n", ret);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    ret = ss_mpi_vi_start_pipe(vi_pipe);
    printf("[VI_REPLAY_PIPE] start_ret=0x%x\n", ret);
    if (ret != TD_SUCCESS) {
        ss_mpi_vi_destroy_pipe(vi_pipe);
        return ret;
    }

    if (DTOF_REPLAY_START_CHN) {
        memcpy(&chn_attr, &vi_cfg.pipe_info[0].chn_info[0].chn_attr, sizeof(chn_attr));
        chn_attr.size.width = DTOF_REPLAY_WIDTH;
        chn_attr.size.height = DTOF_REPLAY_HEIGHT;
        chn_attr.depth = 2;
        ret = ss_mpi_vi_set_chn_attr(vi_pipe, 0, &chn_attr);
        printf("[VI_REPLAY_CHN] set_attr_ret=0x%x pipe=%d chn=0 w=%u h=%u pixfmt=%d depth=%u\n",
            ret,
            vi_pipe,
            chn_attr.size.width,
            chn_attr.size.height,
            chn_attr.pixel_format,
            chn_attr.depth);
        if (ret != TD_SUCCESS) {
            ss_mpi_vi_stop_pipe(vi_pipe);
            ss_mpi_vi_destroy_pipe(vi_pipe);
            return ret;
        }
        ret = ss_mpi_vi_enable_chn(vi_pipe, 0);
        printf("[VI_REPLAY_CHN] enable_ret=0x%x pipe=%d chn=0\n", ret, vi_pipe);
        if (ret != TD_SUCCESS) {
            ss_mpi_vi_stop_pipe(vi_pipe);
            ss_mpi_vi_destroy_pipe(vi_pipe);
            return ret;
        }
    }
    return TD_SUCCESS;
}

static td_void dtof_replay_destroy_pipe(ot_vi_pipe vi_pipe)
{
    td_s32 ret;

    if (DTOF_REPLAY_START_CHN) {
        ret = ss_mpi_vi_disable_chn(vi_pipe, 0);
        printf("[VI_REPLAY_CHN] disable_ret=0x%x pipe=%d chn=0\n", ret, vi_pipe);
    }
    ret = ss_mpi_vi_set_pipe_frame_source(vi_pipe, OT_VI_PIPE_FRAME_SOURCE_FE);
    printf("[VI_REPLAY_PIPE] restore_source_ret=0x%x\n", ret);
    ret = ss_mpi_vi_stop_pipe(vi_pipe);
    printf("[VI_REPLAY_PIPE] stop_ret=0x%x\n", ret);
    ret = ss_mpi_vi_destroy_pipe(vi_pipe);
    printf("[VI_REPLAY_PIPE] destroy_ret=0x%x\n", ret);
}

static td_void dtof_replay_set_dump_attrs(ot_vi_pipe vi_pipe, td_bool enable)
{
    ot_vi_frame_dump_attr attr;
    td_s32 ret;

    memset(&attr, 0, sizeof(attr));
    attr.enable = enable;
    attr.depth = enable ? 2 : 0;

    ret = ss_mpi_vi_set_pipe_frame_dump_attr(vi_pipe, &attr);
    printf("[VI_REPLAY_DUMP] label=pipe set_ret=0x%x enable=%d depth=%u\n", ret, attr.enable, attr.depth);
    ret = ss_mpi_vi_set_pipe_fe_out_frame_dump_attr(vi_pipe, &attr);
    printf("[VI_REPLAY_DUMP] label=fe_out set_ret=0x%x enable=%d depth=%u\n", ret, attr.enable, attr.depth);
    ret = ss_mpi_vi_set_pipe_bas_frame_dump_attr(vi_pipe, &attr);
    printf("[VI_REPLAY_DUMP] label=bas set_ret=0x%x enable=%d depth=%u\n", ret, attr.enable, attr.depth);
}

static td_s32 dtof_replay_send_one(ot_vi_pipe vi_pipe, const dtof_replay_input_frame *input, const char *label)
{
    const ot_video_frame_info *frames[1];
    td_s32 ret;

    frames[0] = &input->frame;
    ret = ss_mpi_vi_send_pipe_raw(vi_pipe, frames, 1, DTOF_REPLAY_TIMEOUT_MS);
    printf("[VI_REPLAY_SEND] label=%s ret=0x%x\n", label, ret);
    if (ret == TD_SUCCESS) {
        usleep(200000);
    }
    return ret;
}

static td_void dtof_replay_save_frame_bytes(const char *label, const ot_video_frame_info *frame_info)
{
    const ot_video_frame *vf = &frame_info->video_frame;
    td_ulong size = (td_ulong)vf->stride[0] * vf->height;
    td_u8 *virt = TD_NULL;
    unsigned long long byte_sum = 0;
    td_u32 nonzero = 0;
    td_u32 row0_sum = 0;
    td_u32 row1_sum = 0;
    td_u32 row2_sum = 0;
    td_u32 sample_len;
    char path[128];
    FILE *fp;

    virt = (td_u8 *)ss_mpi_sys_mmap(vf->phys_addr[0], size);
    if (virt == TD_NULL) {
        printf("[VI_REPLAY_FRAME] label=%s mmap_failed phys=0x%llx size=%llu\n",
            label, (unsigned long long)vf->phys_addr[0], (unsigned long long)size);
        return;
    }

    for (td_ulong i = 0; i < size; i++) {
        byte_sum += virt[i];
        if (virt[i] != 0) {
            nonzero++;
        }
    }
    sample_len = vf->stride[0] < 32 ? vf->stride[0] : 32;
    for (td_u32 i = 0; i < sample_len; i++) {
        row0_sum += virt[i];
        if (vf->height > 1) {
            row1_sum += virt[vf->stride[0] + i];
        }
        if (vf->height > 2) {
            row2_sum += virt[2 * vf->stride[0] + i];
        }
    }

    snprintf(path, sizeof(path), "vi_replay_%s_out.bin", label);
    fp = fopen(path, "wb");
    if (fp != TD_NULL) {
        fwrite(virt, 1, size, fp);
        fclose(fp);
    }

    printf("[VI_REPLAY_FRAME] label=%s w=%u h=%u stride=%u pixfmt=%d compress=%d size=%llu "
        "byte_sum=%llu nonzero=%u row_sum32=%u/%u/%u "
        "row1_first16=%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x "
        "saved=%s\n",
        label,
        vf->width,
        vf->height,
        vf->stride[0],
        vf->pixel_format,
        vf->compress_mode,
        (unsigned long long)size,
        byte_sum,
        nonzero,
        row0_sum,
        row1_sum,
        row2_sum,
        vf->height > 1 ? virt[vf->stride[0] + 0] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 1] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 2] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 3] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 4] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 5] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 6] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 7] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 8] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 9] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 10] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 11] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 12] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 13] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 14] : 0,
        vf->height > 1 ? virt[vf->stride[0] + 15] : 0,
        fp != TD_NULL ? path : "open_failed");

    ss_mpi_sys_munmap(virt, size);
}

static td_bool dtof_replay_is_supported_bayer(ot_pixel_format pixel_format)
{
    return pixel_format == OT_PIXEL_FORMAT_RGB_BAYER_10BPP ||
        pixel_format == OT_PIXEL_FORMAT_RGB_BAYER_12BPP ||
        pixel_format == OT_PIXEL_FORMAT_RGB_BAYER_16BPP;
}

static td_u32 dtof_replay_pixel_bit_width(ot_pixel_format pixel_format)
{
    switch (pixel_format) {
        case OT_PIXEL_FORMAT_RGB_BAYER_10BPP:
            return 10;
        case OT_PIXEL_FORMAT_RGB_BAYER_12BPP:
            return 12;
        case OT_PIXEL_FORMAT_RGB_BAYER_16BPP:
            return 16;
        default:
            return 0;
    }
}

static td_u32 dtof_replay_required_row_bytes(const ot_video_frame *vf)
{
    td_u32 bit_width = dtof_replay_pixel_bit_width(vf->pixel_format);
    return (vf->width * bit_width + 7) / 8;
}

static td_void dtof_replay_print_depth_stats(const char *label, DtofError err, const DtofHandle *handle)
{
    td_u16 sorted[UDP_DATA_PIXEL_NUMBER];
    td_u32 lt1000 = 0;
    td_u32 eq2 = 0;
    td_u32 zero = 0;
    td_u32 unique = 0;
    unsigned long long sum = 0;
    td_u16 last = 0;

    if (handle == TD_NULL || handle->dtofOutput.distance == TD_NULL) {
        printf("[VI_REPLAY_DTOF] label=%s ret=%d error=no_distance\n", label, err);
        return;
    }

    for (td_u32 i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
        td_u16 value = handle->dtofOutput.distance[i];
        sorted[i] = value;
        sum += value;
        if (value < 1000) {
            lt1000++;
        }
        if (value == 2) {
            eq2++;
        }
        if (value == 0) {
            zero++;
        }
    }
    qsort(sorted, UDP_DATA_PIXEL_NUMBER, sizeof(sorted[0]), dtof_replay_cmp_u16);
    for (td_u32 i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
        if (i == 0 || sorted[i] != last) {
            unique++;
            last = sorted[i];
        }
    }

    printf("[VI_REPLAY_DTOF] label=%s ret=%d min=%u p25=%u median=%u p75=%u max=%u "
        "mean=%.2f lt1000=%u eq2=%u zero=%u unique=%u center=%u switch=%d config=%d temp=%.2f\n",
        label,
        err,
        sorted[0],
        sorted[UDP_DATA_PIXEL_NUMBER / 4],
        sorted[UDP_DATA_PIXEL_NUMBER / 2],
        sorted[(UDP_DATA_PIXEL_NUMBER * 3) / 4],
        sorted[UDP_DATA_PIXEL_NUMBER - 1],
        (double)sum / (double)UDP_DATA_PIXEL_NUMBER,
        lt1000,
        eq2,
        zero,
        unique,
        handle->dtofOutput.distance[MID_PIXEL],
        handle->dtofOutput.switchFlag,
        handle->dtofOutput.configFlag,
        handle->temperature);
}

static td_void dtof_replay_try_process_frame(const char *label, ot_video_frame_info *frame_info, DtofHandle *handle)
{
    ot_video_frame *vf = &frame_info->video_frame;
    td_u32 required;
    td_u16 *data = TD_NULL;
    DtofError err;

    if (handle == TD_NULL) {
        printf("[VI_REPLAY_DTOF] label=%s skip=no_handle\n", label);
        return;
    }
    if (vf->compress_mode != OT_COMPRESS_MODE_NONE) {
        printf("[VI_REPLAY_DTOF] label=%s skip=compressed_frame compress=%d\n", label, vf->compress_mode);
        return;
    }
    if (!dtof_replay_is_supported_bayer(vf->pixel_format)) {
        printf("[VI_REPLAY_DTOF] label=%s skip=unsupported_pixfmt pixfmt=%d\n", label, vf->pixel_format);
        return;
    }
    if (vf->height < HEIGHT + 1) {
        printf("[VI_REPLAY_DTOF] label=%s skip=short_height height=%u\n", label, vf->height);
        return;
    }
    required = dtof_replay_required_row_bytes(vf);
    if (vf->stride[0] < required) {
        printf("[VI_REPLAY_DTOF] label=%s skip=row_overread_risk stride=%u required=%u\n",
            label, vf->stride[0], required);
        return;
    }

    data = deal_frame_data(frame_info);
    if (data == TD_NULL) {
        printf("[VI_REPLAY_DTOF] label=%s skip=deal_frame_data_failed\n", label);
        return;
    }

    handle->data = data;
    handle->dataLen = HEIGHT * WEIGHT * BIN_NUM;
    err = DtofProcess(handle);
    dtof_replay_print_depth_stats(label, err, handle);
    free(data);
    handle->data = TD_NULL;
}

static td_s32 dtof_replay_get_pipe(ot_vi_pipe vi_pipe, ot_video_frame_info *frame, td_s32 timeout)
{
    return ss_mpi_vi_get_pipe_frame(vi_pipe, frame, timeout);
}

static td_s32 dtof_replay_release_pipe(ot_vi_pipe vi_pipe, const ot_video_frame_info *frame)
{
    return ss_mpi_vi_release_pipe_frame(vi_pipe, frame);
}

static td_s32 dtof_replay_get_fe_out(ot_vi_pipe vi_pipe, ot_video_frame_info *frame, td_s32 timeout)
{
    return ss_mpi_vi_get_pipe_fe_out_frame(vi_pipe, frame, timeout);
}

static td_s32 dtof_replay_release_fe_out(ot_vi_pipe vi_pipe, const ot_video_frame_info *frame)
{
    return ss_mpi_vi_release_pipe_fe_out_frame(vi_pipe, frame);
}

static td_s32 dtof_replay_get_bas(ot_vi_pipe vi_pipe, ot_video_frame_info *frame, td_s32 timeout)
{
    return ss_mpi_vi_get_pipe_bas_frame(vi_pipe, frame, timeout);
}

static td_s32 dtof_replay_release_bas(ot_vi_pipe vi_pipe, const ot_video_frame_info *frame)
{
    return ss_mpi_vi_release_pipe_bas_frame(vi_pipe, frame);
}

static td_s32 dtof_replay_try_output(const char *label, ot_vi_pipe vi_pipe, const dtof_replay_input_frame *input,
    DtofHandle *handle,
    td_s32 (*get_frame)(ot_vi_pipe, ot_video_frame_info *, td_s32),
    td_s32 (*release_frame)(ot_vi_pipe, const ot_video_frame_info *))
{
    ot_video_frame_info frame_info;
    td_s32 ret;

    ret = dtof_replay_send_one(vi_pipe, input, label);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    memset(&frame_info, 0, sizeof(frame_info));
    ret = get_frame(vi_pipe, &frame_info, DTOF_REPLAY_TIMEOUT_MS);
    printf("[VI_REPLAY_GET] label=%s ret=0x%x\n", label, ret);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    dtof_replay_save_frame_bytes(label, &frame_info);
    dtof_replay_try_process_frame(label, &frame_info, handle);
    ret = release_frame(vi_pipe, &frame_info);
    printf("[VI_REPLAY_RELEASE] label=%s ret=0x%x\n", label, ret);
    return ret;
}

td_s32 dtof_vi_user_replay_main(td_s32 argc, td_char *argv[])
{
    const char *path;
    td_u8 *raw = TD_NULL;
    td_u32 raw_len = 0;
    ot_vb_calc_cfg calc_cfg;
    dtof_replay_input_frame input;
    ot_vi_pipe vi_pipe = 1;
    ot_vi_dev vi_dev = DTOF_REPLAY_DEFAULT_DEV;
    td_bool sys_started = TD_FALSE;
    td_bool dev_bound = TD_FALSE;
    td_bool pipe_started = TD_FALSE;
    td_s32 ret = TD_FAILURE;
    DtofHandleConfig config;
    DtofHandle *handle = TD_NULL;

    if (argc < 2) {
        printf("usage: %s <dtof_line_dump_fNNN.bin> [vi_pipe]\n", argv[0]);
        return TD_FAILURE;
    }
    path = argv[1];
    if (argc >= 3) {
        vi_pipe = atoi(argv[2]);
    }
    if (argc >= 4) {
        vi_dev = atoi(argv[3]);
    }

    memset(&input, 0, sizeof(input));
    input.pool = OT_VB_INVALID_POOL_ID;
    input.blk = OT_VB_INVALID_HANDLE;

    if (dtof_replay_read_file(path, &raw, &raw_len) != TD_SUCCESS) {
        goto cleanup;
    }

    memset(&calc_cfg, 0, sizeof(calc_cfg));
    dtof_replay_calc_input_buf(&calc_cfg);
    printf("[VI_REPLAY_START] path=%s raw_len=%u dev=%d pipe=%d use_dev_bind=%d "
        "pipe_bypass=%d pipe_compress=%d input_compress=%d "
        "calc_vb_size=%llu calc_stride=%u calc_y=%u eeprom_len=%u\n",
        path,
        raw_len,
        vi_dev,
        vi_pipe,
        DTOF_REPLAY_USE_DEV_BIND,
        DTOF_REPLAY_PIPE_BYPASS,
        DTOF_REPLAY_PIPE_COMPRESS,
        DTOF_REPLAY_INPUT_COMPRESS,
        (unsigned long long)calc_cfg.vb_size,
        calc_cfg.main_stride,
        calc_cfg.main_y_size,
        (td_u32)sizeof(g_dtof_replay_eeprom));

    if (dtof_replay_sys_init(calc_cfg.vb_size) != TD_SUCCESS) {
        goto cleanup;
    }
    sys_started = TD_TRUE;

    if (dtof_replay_alloc_input_frame(&input, raw, raw_len, &calc_cfg) != TD_SUCCESS) {
        goto cleanup;
    }

    if (DTOF_REPLAY_USE_DEV_BIND) {
        if (dtof_replay_start_dev_bind(vi_dev, vi_pipe) != TD_SUCCESS) {
            goto cleanup;
        }
        dev_bound = TD_TRUE;
    }

    if (dtof_replay_create_pipe(vi_pipe) != TD_SUCCESS) {
        goto cleanup;
    }
    pipe_started = TD_TRUE;

    dtof_replay_set_dump_attrs(vi_pipe, TD_TRUE);

    ret = ss_mpi_vi_set_pipe_frame_source(vi_pipe, OT_VI_PIPE_FRAME_SOURCE_USER);
    printf("[VI_REPLAY_PIPE] set_source_user_ret=0x%x\n", ret);
    if (ret != TD_SUCCESS) {
        goto cleanup;
    }

    memset(&config, 0, sizeof(config));
    config.iniFile = DTOF_INI_FILE_PATH;
    config.spotFile = DTOF_SPOT_FILE_PATH;
    memcpy(config.dtofCalibPara, g_dtof_replay_eeprom, sizeof(g_dtof_replay_eeprom));
    handle = DtofInit(&config);
    printf("[VI_REPLAY_DTOF_INIT] handle=%p\n", (void *)handle);

    (void)dtof_replay_try_output("pipe", vi_pipe, &input, handle,
        dtof_replay_get_pipe, dtof_replay_release_pipe);
    (void)dtof_replay_try_output("fe_out", vi_pipe, &input, handle,
        dtof_replay_get_fe_out, dtof_replay_release_fe_out);
    (void)dtof_replay_try_output("bas", vi_pipe, &input, handle,
        dtof_replay_get_bas, dtof_replay_release_bas);

    ret = TD_SUCCESS;

cleanup:
    if (handle != TD_NULL) {
        if (handle->data != TD_NULL) {
            free(handle->data);
            handle->data = TD_NULL;
        }
        DtofDestory(handle);
    }
    if (pipe_started == TD_TRUE) {
        dtof_replay_set_dump_attrs(vi_pipe, TD_FALSE);
        dtof_replay_destroy_pipe(vi_pipe);
    }
    if (dev_bound == TD_TRUE) {
        dtof_replay_stop_dev_bind(vi_dev, vi_pipe);
    }
    dtof_replay_free_input_frame(&input);
    if (sys_started == TD_TRUE) {
        sample_comm_sys_exit();
        printf("[VI_REPLAY_SYS] sample_comm_sys_exit_done\n");
    }
    if (raw != TD_NULL) {
        free(raw);
    }
    printf("[VI_REPLAY_DONE] ret=0x%x\n", ret);
    return ret;
}
#endif

'''
helper = helper_template.replace("__EEPROM_ARRAY__", eeprom_array)
if helper_marker not in text:
    raise SystemExit("dtof_init marker not found")
text = text.replace(helper_marker, helper + helper_marker, 1)
dump.write_text(text)

sample = Path("src/dtof/sample_dtof.c")
text = sample.read_text()
main_marker = "#endif\n{\n    td_s32 ret;\n"
replacement = (
    "#endif\n"
    "{\n"
    "#ifdef DTOF_VI_USER_REPLAY\n"
    "    extern td_s32 dtof_vi_user_replay_main(td_s32 argc, td_char *argv[]);\n"
    "    return dtof_vi_user_replay_main(argc, argv);\n"
    "#endif\n"
    "    td_s32 ret;\n"
)
if main_marker not in text:
    raise SystemExit("main marker not found")
text = text.replace(main_marker, replacement, 1)
sample.write_text(text)

makefile = Path("src/dtof/Makefile")
text = makefile.read_text()
if "CFLAGS += $(EXTRA_CFLAGS)" not in text:
    marker = "MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a\n"
    if marker not in text:
        raise SystemExit("Makefile marker not found")
    text = text.replace(marker, marker + "\nCFLAGS += $(EXTRA_CFLAGS)\n", 1)
    makefile.write_text(text)
    print("VI_USER_REPLAY_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("VI_USER_REPLAY_PATCH EXTRA_CFLAGS hook already present")
print("VI_USER_REPLAY_PATCH applied")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_vi_user_replay_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA_CFLAGS" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_vi_user_replay_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
strings "$BINARY_NAME" > /tmp/dtof_vi_user_replay_strings.log
grep -q "VI_REPLAY" /tmp/dtof_vi_user_replay_strings.log
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
