#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_offline_line_sweep_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
EEPROM_BIN="${EEPROM_BIN:-/home/ebaina/gs1860_eeprom_521.bin}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_offline_line_sweep_dbg}"
EXTRA_CFLAGS="${EXTRA_CFLAGS:--DDTOF_OFFLINE_LINE_SWEEP}"
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
#ifdef DTOF_OFFLINE_LINE_SWEEP
#define DTOF_OFFLINE_EEPROM_LEN 521
#define DTOF_OFFLINE_HEADER_BYTES 16
#define DTOF_OFFLINE_MASK_WORDS (WEIGHT * (BIN_NUM / 32))
#define DTOF_OFFLINE_MODE_BIT_REVERSE 1
#define DTOF_OFFLINE_MODE_HALF_SWAP 2
#define DTOF_OFFLINE_MODE_BIN_INVERT 4

static const td_u8 g_dtof_offline_eeprom[DTOF_OFFLINE_EEPROM_LEN] = { __EEPROM_ARRAY__ };

static int dtof_offline_cmp_u16(const void *a, const void *b)
{
    td_u16 va = *(const td_u16 *)a;
    td_u16 vb = *(const td_u16 *)b;
    return (va > vb) - (va < vb);
}

static td_s32 dtof_offline_read_file(const char *path, td_u8 **data, td_u32 *len)
{
    FILE *fp;
    long size;
    size_t got;

    if (path == TD_NULL || data == TD_NULL || len == TD_NULL) {
        return TD_FAILURE;
    }

    fp = fopen(path, "rb");
    if (fp == TD_NULL) {
        printf("[OFFLINE_SWEEP_ERROR] open_failed path=%s errno=%d\n", path, errno);
        return TD_FAILURE;
    }
    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return TD_FAILURE;
    }
    size = ftell(fp);
    if (size <= 0 || size > 1024 * 1024) {
        fclose(fp);
        printf("[OFFLINE_SWEEP_ERROR] bad_size path=%s size=%ld\n", path, size);
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

static td_s32 dtof_offline_one_zero_bit_index(td_u32 word)
{
    td_u32 diff = ~word;
    td_s32 bit;

    if (diff == 0 || (diff & (diff - 1)) != 0) {
        return -1;
    }
    for (bit = 0; bit < 32; bit++) {
        if ((diff & (1U << bit)) != 0) {
            return bit;
        }
    }
    return -1;
}

static td_u32 dtof_offline_fill_zero(td_u16 *hist)
{
    (td_void)memset_s(hist, sizeof(td_u16) * HEIGHT * WEIGHT * BIN_NUM,
        0, sizeof(td_u16) * HEIGHT * WEIGHT * BIN_NUM);
    return 0;
}

static td_u32 dtof_offline_fill_mask_variant(const td_u8 *raw, td_u32 raw_len,
    td_u16 *hist, td_u32 amplitude, td_u32 mode)
{
    td_u32 stride;
    td_u32 row;
    td_u32 col;
    td_u32 half;
    td_u32 active_bins = 0;

    if (raw == TD_NULL || hist == TD_NULL || raw_len % (HEIGHT + 1) != 0) {
        return 0;
    }
    stride = raw_len / (HEIGHT + 1);
    if (stride < DTOF_OFFLINE_HEADER_BYTES + DTOF_OFFLINE_MASK_WORDS * sizeof(td_u32)) {
        return 0;
    }

    (td_void)memset_s(hist, sizeof(td_u16) * HEIGHT * WEIGHT * BIN_NUM,
        0, sizeof(td_u16) * HEIGHT * WEIGHT * BIN_NUM);

    for (row = 0; row < HEIGHT; row++) {
        const td_u8 *row_ptr = raw + (row + 1) * stride + DTOF_OFFLINE_HEADER_BYTES;
        for (col = 0; col < WEIGHT; col++) {
            for (half = 0; half < 2; half++) {
                td_u32 word = 0;
                td_u32 out_half = half;
                td_u32 bin;
                td_s32 bit;

                (td_void)memcpy_s(&word, sizeof(word), row_ptr + (col * 2 + half) * sizeof(td_u32), sizeof(word));
                bit = dtof_offline_one_zero_bit_index(word);
                if (bit < 0) {
                    continue;
                }
                if ((mode & DTOF_OFFLINE_MODE_BIT_REVERSE) != 0) {
                    bit = 31 - bit;
                }
                if ((mode & DTOF_OFFLINE_MODE_HALF_SWAP) != 0) {
                    out_half = 1 - out_half;
                }
                bin = out_half * 32 + (td_u32)bit;
                if ((mode & DTOF_OFFLINE_MODE_BIN_INVERT) != 0) {
                    bin = BIN_NUM - 1 - bin;
                }
                hist[row * WEIGHT * BIN_NUM + col * BIN_NUM + bin] = (td_u16)amplitude;
                active_bins++;
            }
        }
    }
    return active_bins;
}

static td_void dtof_offline_print_depth_stats(const char *variant, td_u32 amplitude,
    td_u32 active_bins, DtofError err, DtofHandle *handle)
{
    td_u16 sorted[UDP_DATA_PIXEL_NUMBER];
    td_u32 i;
    td_u32 lt1000 = 0;
    td_u32 eq2 = 0;
    td_u32 zero = 0;
    td_u32 unique = 0;
    unsigned long long sum = 0;
    float mean;
    td_u16 last = 0;

    if (handle == TD_NULL || handle->dtofOutput.distance == TD_NULL) {
        printf("[OFFLINE_SWEEP] variant=%s amplitude=%u active_bins=%u ret=%d error=no_distance\n",
            variant, amplitude, active_bins, err);
        return;
    }

    for (i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
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
    qsort(sorted, UDP_DATA_PIXEL_NUMBER, sizeof(sorted[0]), dtof_offline_cmp_u16);
    for (i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
        if (i == 0 || sorted[i] != last) {
            unique++;
            last = sorted[i];
        }
    }
    mean = (float)((double)sum / (double)UDP_DATA_PIXEL_NUMBER);
    printf("[OFFLINE_SWEEP] variant=%s amplitude=%u active_bins=%u ret=%d "
        "min=%u p25=%u median=%u p75=%u max=%u mean=%.2f lt1000=%u eq2=%u zero=%u unique=%u center=%u\n",
        variant,
        amplitude,
        active_bins,
        err,
        sorted[0],
        sorted[UDP_DATA_PIXEL_NUMBER / 4],
        sorted[UDP_DATA_PIXEL_NUMBER / 2],
        sorted[(UDP_DATA_PIXEL_NUMBER * 3) / 4],
        sorted[UDP_DATA_PIXEL_NUMBER - 1],
        mean,
        lt1000,
        eq2,
        zero,
        unique,
        handle->dtofOutput.distance[MID_PIXEL]);
}

static td_s32 dtof_offline_run_variant(DtofHandle *handle, const char *variant,
    td_u32 amplitude, td_u32 active_bins)
{
    DtofError err;

    if (handle == TD_NULL || handle->data == TD_NULL) {
        return TD_FAILURE;
    }
    err = DtofProcess(handle);
    dtof_offline_print_depth_stats(variant, amplitude, active_bins, err, handle);
    return TD_SUCCESS;
}

td_s32 dtof_offline_line_sweep_main(td_s32 argc, td_char *argv[])
{
    static td_u32 amplitudes[] = {512, 1024, 2048, 4095, 8191, 16383, 32767, 65535};
    td_u8 *raw = TD_NULL;
    td_u32 raw_len = 0;
    td_u32 stride = 0;
    DtofHandleConfig config;
    DtofHandle *handle = TD_NULL;
    td_u32 active_bins;
    td_u32 amp_idx;
    td_u32 mode;
    td_s32 ret = TD_FAILURE;

    if (argc < 2) {
        printf("usage: %s <dtof_line_dump_fNNN.bin>\n", argv[0]);
        return TD_FAILURE;
    }

    if (dtof_offline_read_file(argv[1], &raw, &raw_len) != TD_SUCCESS) {
        return TD_FAILURE;
    }
    if (raw_len % (HEIGHT + 1) == 0) {
        stride = raw_len / (HEIGHT + 1);
    }
    printf("[OFFLINE_SWEEP_INPUT] path=%s raw_len=%u stride_guess=%u eeprom_len=%u\n",
        argv[1], raw_len, stride, (td_u32)sizeof(g_dtof_offline_eeprom));

    (td_void)memset_s(&config, sizeof(config), 0, sizeof(config));
    config.iniFile = DTOF_INI_FILE_PATH;
    config.spotFile = DTOF_SPOT_FILE_PATH;
    (td_void)memcpy_s(config.dtofCalibPara, sizeof(config.dtofCalibPara),
        g_dtof_offline_eeprom, sizeof(g_dtof_offline_eeprom));

    handle = DtofInit(&config);
    if (handle == TD_NULL) {
        printf("[OFFLINE_SWEEP_ERROR] DtofInit failed\n");
        goto cleanup;
    }
    handle->data = (td_u16 *)malloc(sizeof(td_u16) * HEIGHT * WEIGHT * BIN_NUM);
    if (handle->data == TD_NULL) {
        printf("[OFFLINE_SWEEP_ERROR] data malloc failed\n");
        goto cleanup;
    }
    handle->dataLen = HEIGHT * WEIGHT * BIN_NUM;

    active_bins = dtof_offline_fill_zero(handle->data);
    (td_void)dtof_offline_run_variant(handle, "zero", 0, active_bins);

    for (mode = 0; mode < 8; mode++) {
        for (amp_idx = 0; amp_idx < sizeof(amplitudes) / sizeof(amplitudes[0]); amp_idx++) {
            char variant[64] = {0};
            (td_void)snprintf_s(variant, sizeof(variant), sizeof(variant) - 1,
                "mask_m%u", mode);
            active_bins = dtof_offline_fill_mask_variant(raw, raw_len, handle->data, amplitudes[amp_idx], mode);
            (td_void)dtof_offline_run_variant(handle, variant, amplitudes[amp_idx], active_bins);
        }
    }

    ret = TD_SUCCESS;

cleanup:
    if (handle != TD_NULL) {
        if (handle->data != TD_NULL) {
            free(handle->data);
            handle->data = TD_NULL;
        }
        DtofDestory(handle);
    }
    if (raw != TD_NULL) {
        free(raw);
    }
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
    "#ifdef DTOF_OFFLINE_LINE_SWEEP\n"
    "    extern td_s32 dtof_offline_line_sweep_main(td_s32 argc, td_char *argv[]);\n"
    "    return dtof_offline_line_sweep_main(argc, argv);\n"
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
    print("OFFLINE_LINE_SWEEP_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("OFFLINE_LINE_SWEEP_PATCH EXTRA_CFLAGS hook already present")
print("OFFLINE_LINE_SWEEP_PATCH applied")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_offline_line_sweep_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA_CFLAGS" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_offline_line_sweep_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
strings "$BINARY_NAME" > /tmp/dtof_offline_line_sweep_strings.log
grep -q "OFFLINE_SWEEP" /tmp/dtof_offline_line_sweep_strings.log
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
