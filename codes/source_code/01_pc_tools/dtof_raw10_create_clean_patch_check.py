#!/usr/bin/env python3
"""Dry-run check for the clean RAW10/NONE-at-creation dToF patch.

This tool reads the clean SDK zip or an extracted SDK tree, applies the same textual
anchors used by vm_build_official_raw10_create_clean.sh in memory, and reports whether
the route2 build script should reach compilation. It does not modify any source files.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


SAMPLE_REL = "src/dtof/sample_dtof.c"
COMMON_REL = "src/common/sample_comm_vi.c"
DUMP_REL = "src/dtof/dtof_dumpraw.c"
MAKEFILE_REL = "src/dtof/Makefile"


def _read_from_zip(zip_path: Path, rel: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        matches = [name for name in zf.namelist() if name.replace("\\", "/").endswith(rel)]
        if len(matches) != 1:
            raise SystemExit(f"expected one {rel} in {zip_path}, found {len(matches)}")
        return zf.read(matches[0]).decode("utf-8", errors="replace")


def _read_source(source: Path, rel: str) -> str:
    if source.suffix.lower() == ".zip":
        return _read_from_zip(source, rel)
    return (source / rel).read_text(encoding="utf-8", errors="replace")


def _require(text: str, needle: str, label: str) -> int:
    count = text.count(needle)
    if count == 0:
        raise SystemExit(f"missing anchor: {label}")
    return count


def check(source: Path) -> dict[str, int | bool]:
    sample = _read_source(source, SAMPLE_REL)
    common = _read_source(source, COMMON_REL)
    dump = _read_source(source, DUMP_REL)
    makefile = _read_source(source, MAKEFILE_REL)

    old_sig = (
        "static td_void sample_dtof_get_default_vb_config(ot_size *size, ot_vb_cfg *vb_cfg, "
        "ot_vi_video_mode video_mode,\n"
        "    td_u32 yuv_cnt, td_u32 raw_cnt)\n"
    )
    old_call = "    sample_dtof_get_default_vb_config(&size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);\n"
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
    pipe_bypass = "        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;\n"
    pipe_bypass_repl = pipe_bypass + (
        "#ifdef DTOF_FORCE_RAW10_NONE\n"
        "        vi_cfg->pipe_info[0].pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10;\n"
        "        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;\n"
        "        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;\n"
        "#endif\n"
    )
    marker = "static volatile sig_atomic_t g_sig_flag = 0;\n"
    print_anchor = "static td_void sample_get_char(td_void)\n"
    start_anchor = "    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[0], sensor_num);\n"
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
    make_marker = "MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a\n"
    new_sig = (
        "static td_void sample_dtof_get_default_vb_config(sample_sns_type sns_type, ot_size *size, "
        "ot_vb_cfg *vb_cfg,\n"
        "    ot_vi_video_mode video_mode, td_u32 yuv_cnt, td_u32 raw_cnt)\n"
    )
    new_call = "    sample_dtof_get_default_vb_config(sns_type, &size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);\n"

    counts = {
        "old_sig": _require(sample, old_sig, "vb config signature"),
        "old_call": _require(sample, old_call, "vb config call"),
        "vb_raw_anchor": _require(sample, vb_raw_anchor, "raw VB pool"),
        "dtof_bypass_blocks": sample.count(pipe_bypass),
        "sample_marker": _require(sample, marker, "g_sig_flag marker"),
        "sample_get_char": _require(sample, print_anchor, "sample_get_char"),
        "one_dtof_anchor": sample.count(start_anchor),
        "common_vi_blocks": common.count(sony_raw10),
        "dump_keepattr_already": "#ifndef DTOF_KEEP_PIPE_ATTR" in dump,
        "dump_pipe_attr_blocks": dump.count(dump_attr_block),
        "makefile_extra_hook": "CFLAGS += $(EXTRA_CFLAGS)" in makefile,
        "makefile_marker": _require(makefile, make_marker, "Makefile libdepth_process marker"),
    }

    expected_exact = {
        "dtof_bypass_blocks": 2,
        "one_dtof_anchor": 1,
        "common_vi_blocks": 2,
        "dump_pipe_attr_blocks": 1,
    }
    for key, expected in expected_exact.items():
        if counts[key] != expected:
            raise SystemExit(f"{key}: expected {expected}, found {counts[key]}")

    patched_sample = sample
    patched_sample = patched_sample.replace(old_sig, new_sig, 1)
    patched_sample = patched_sample.replace(old_call, new_call, 1)
    patched_sample = patched_sample.replace(vb_raw_anchor, vb_raw_repl, 1)
    patched_sample = patched_sample.replace(pipe_bypass, pipe_bypass_repl)
    patched_sample = patched_sample.replace(
        marker,
        marker + "\nstatic const char *g_dtof_raw10_create_marker = \"DTOF_RAW10_CREATE_CLEAN\";\n",
        1,
    )
    patched_sample = patched_sample.replace(
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
    patched_sample = patched_sample.replace(
        start_anchor,
        "    sample_dtof_print_raw10_create_marker();\n" + start_anchor,
        1,
    )
    patched_common = common.replace(sony_raw10, gs1860_raw10)
    patched_dump = dump.replace(dump_attr_block, dump_keepattr_block, 1)
    patched_makefile = makefile
    if "CFLAGS += $(EXTRA_CFLAGS)" not in patched_makefile:
        patched_makefile = patched_makefile.replace(make_marker, make_marker + "\nCFLAGS += $(EXTRA_CFLAGS)\n", 1)

    counts.update(
        {
            "patched_sig": patched_sample.count("sample_dtof_get_default_vb_config(sample_sns_type sns_type"),
            "patched_call": patched_sample.count(new_call),
            "patched_marker": patched_sample.count("DTOF_RAW10_CREATE_CLEAN"),
            "patched_marker_call": patched_sample.count("sample_dtof_print_raw10_create_marker();"),
            "patched_sample_pipe_bitwidth10": patched_sample.count(
                "vi_cfg->pipe_info[0].pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10;"
            ),
            "patched_sample_vb_bitwidth10": patched_sample.count("buf_attr.bit_width = OT_DATA_BIT_WIDTH_10;"),
            "patched_common_gs1860_overrides": patched_common.count(
                "if (sns_type == HISI_GS1860_MIPI_1M_30FPS_10BIT)"
            ),
            "patched_dump_keepattr_blocks": patched_dump.count("#ifndef DTOF_KEEP_PIPE_ATTR"),
            "patched_makefile_extra_hook": "CFLAGS += $(EXTRA_CFLAGS)" in patched_makefile,
        }
    )

    patched_expected = {
        "patched_sig": 1,
        "patched_call": 1,
        "patched_marker": 2,
        "patched_marker_call": 1,
        "patched_sample_pipe_bitwidth10": 2,
        "patched_sample_vb_bitwidth10": 1,
        "patched_common_gs1860_overrides": 2,
        "patched_dump_keepattr_blocks": 1,
    }
    for key, expected in patched_expected.items():
        if counts[key] != expected:
            raise SystemExit(f"{key}: expected {expected}, found {counts[key]}")
    if not counts["patched_makefile_extra_hook"]:
        raise SystemExit("patched Makefile is missing EXTRA_CFLAGS hook")

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        default="vendor/SS928V100_dtof_build_source.zip",
        help="SDK zip or extracted SDK root to check",
    )
    args = parser.parse_args(argv)

    counts = check(Path(args.source))
    print("DTOF_RAW10_CREATE_CLEAN_PATCH_CHECK=PASS")
    for key in sorted(counts):
        print(f"{key}={counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
