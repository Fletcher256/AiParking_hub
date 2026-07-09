#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
BUILD="${BUILD:-/home/ebaina/official_dtof_eeprom_dump_${timestamp}}"
ZIP="${ZIP:-/home/ebaina/ZZIP/SS928V100_dtof_build_source.zip}"
TOOLCHAIN="/opt/linux/x86-arm/aarch64-mix210-linux/bin:/opt/linux/x86-arm/aarch64-mix210-linux/host_bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
BINARY_NAME="${BINARY_NAME:-sample_dtof_official_eeprom_dump_dbg}"
EXTRA_CFLAGS="${EXTRA_CFLAGS:--DDTOF_EEPROM_DUMP_ONLY}"
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

dump = Path("src/dtof/dtof_dumpraw.c")
text = dump.read_text()

helper_marker = "td_s32 dtof_init(ot_vi_pipe vi_pipe, td_char* serverip)\n"
helper = r'''
#ifdef DTOF_EEPROM_DUMP_ONLY
static td_void dtof_print_eeprom_dump(const td_u8 *data, td_u32 len, td_s32 read_ret)
{
    td_u32 i;
    td_u32 nonzero = 0;
    td_u32 byte_sum = 0;

    if (data == TD_NULL) {
        printf("[DTOF_EEPROM] ret=0x%x len=0 error=null_data\n", read_ret);
        fflush(stdout);
        return;
    }

    for (i = 0; i < len; i++) {
        if (data[i] != 0) {
            nonzero++;
        }
        byte_sum += data[i];
    }

    printf("[DTOF_EEPROM] ret=0x%x len=%u nonzero=%u byte_sum=%u hex=", read_ret, len, nonzero, byte_sum);
    for (i = 0; i < len; i++) {
        printf("%02x", data[i]);
    }
    printf("\n");
    printf("[DTOF_EEPROM_FIRST64] ");
    for (i = 0; i < len && i < 64; i++) {
        printf("%02x%s", data[i], (i + 1 == len || i == 63) ? "" : " ");
    }
    printf("\n");
    fflush(stdout);
}
#endif

'''
if helper_marker not in text:
    raise SystemExit("dtof_init marker not found")
text = text.replace(helper_marker, helper + helper_marker, 1)

old = (
    "    gs1860_read_eeprom(vi_pipe, (unsigned char*)&(g_handle_config->dtofCalibPara), sizeof(g_handle_config->dtofCalibPara));\n"
    "\n"
    "    g_handle = DtofInit(g_handle_config);\n"
)
new = (
    "    td_u8 *calib_data = (td_u8 *)&(g_handle_config->dtofCalibPara);\n"
    "    td_u32 calib_len = sizeof(g_handle_config->dtofCalibPara);\n"
    "    td_s32 eeprom_ret = gs1860_read_eeprom(vi_pipe, calib_data, calib_len);\n"
    "\n"
    "#ifdef DTOF_EEPROM_DUMP_ONLY\n"
    "    dtof_print_eeprom_dump(calib_data, calib_len, eeprom_ret);\n"
    "    free(g_handle_config);\n"
    "    g_handle_config = TD_NULL;\n"
    "    return eeprom_ret == TD_SUCCESS ? TD_SUCCESS : TD_FAILURE;\n"
    "#endif\n"
    "\n"
    "    g_handle = DtofInit(g_handle_config);\n"
)
if old not in text:
    raise SystemExit("gs1860_read_eeprom block not found")
text = text.replace(old, new, 1)
dump.write_text(text)

sample = Path("src/dtof/sample_dtof.c")
text = sample.read_text()
anchor = (
    "    ret = dtof_init(vi_pipe, server_ip);\n"
    "    if (ret != TD_SUCCESS) {\n"
    "        sample_print(\"dtof init failed\\n\");\n"
    "        goto dtof_init_failed;\n"
    "    }\n"
)
insert = anchor + (
    "\n"
    "#ifdef DTOF_EEPROM_DUMP_ONLY\n"
    "    sample_print(\"dtof eeprom dump only: skip vi_bayerdump and UDP depth output\\n\");\n"
    "    goto dtof_init_failed;\n"
    "#endif\n"
)
count = text.count(anchor)
if count < 1:
    raise SystemExit("dtof_init anchor for one-dtof function not found")
text = text.replace(anchor, insert, 1)

anchor_array = (
    "    ret = dtof_init(vi_pipe[1], server_ip);\n"
    "    if (ret != TD_SUCCESS) {\n"
    "        sample_print(\"dtof init failed\\n\");\n"
    "        goto dtof_init_failed;\n"
    "    }\n"
)
insert_array = anchor_array + (
    "\n"
    "#ifdef DTOF_EEPROM_DUMP_ONLY\n"
    "    sample_print(\"dtof eeprom dump only: skip vi_bayerdump and UDP depth output\\n\");\n"
    "    goto dtof_init_failed;\n"
    "#endif\n"
)
array_count = text.count(anchor_array)
if array_count < 1:
    raise SystemExit("dtof_init anchor for rgb+dtof function not found")
text = text.replace(anchor_array, insert_array)

sample.write_text(text)
print(f"EEPROM_DUMP_PATCH one_pipe_blocks={count} array_pipe_blocks={array_count}")

makefile = Path("src/dtof/Makefile")
text = makefile.read_text()
if "CFLAGS += $(EXTRA_CFLAGS)" not in text:
    marker = "MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a\n"
    if marker not in text:
        raise SystemExit("Makefile marker not found")
    text = text.replace(marker, marker + "\nCFLAGS += $(EXTRA_CFLAGS)\n", 1)
    makefile.write_text(text)
    print("EEPROM_DUMP_PATCH inserted EXTRA_CFLAGS hook")
else:
    print("EEPROM_DUMP_PATCH EXTRA_CFLAGS hook already present")
PY

cd "$BUILD/src/dtof"
env PATH="$TOOLCHAIN" make clean >/tmp/dtof_eeprom_dump_clean.log 2>&1 || true
env PATH="$TOOLCHAIN" make OS_TYPE=linux \
  EXTRA_CFLAGS="$EXTRA_CFLAGS" \
  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR1_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  SENSOR3_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
  all 2>&1 | tee /tmp/dtof_eeprom_dump_build.log >/dev/null

cp sample_dtof "$BINARY_NAME"
sha256sum "$BINARY_NAME"
ls -l "$BINARY_NAME"
strings "$BINARY_NAME" | grep -q "DTOF_EEPROM" || {
  echo "warning: DTOF_EEPROM marker was not found by strings; binary was still produced" >&2
}
echo "BUILD_DIR=$BUILD"
echo "BINARY=$BUILD/src/dtof/$BINARY_NAME"
