#!/usr/bin/env python3
"""Validate official dToF UDP packets on the Ubuntu VM.

This helper only connects to the VM and listens on UDP/2368. It does not
control the board. Use it while an approved board-side sample_dtof case is
running.
"""

from __future__ import annotations

import argparse
import textwrap


DEFAULT_HOST = "192.168.137.100"
DEFAULT_USER = "ebaina"
DEFAULT_PASSWORD = "ebaina"
DTOF_PORT = 2368
EXPECTED_PAYLOAD_SIZE = 4873
EXPECTED_WIDTH = 40
EXPECTED_HEIGHT = 30
WIDTH_OFFSET = 18
HEIGHT_OFFSET = 20


def build_remote_script(seconds: int, max_packets: int) -> str:
    return f"""
import socket
import struct
import time
from collections import Counter

PORT = {DTOF_PORT}
EXPECTED_SIZE = {EXPECTED_PAYLOAD_SIZE}
EXPECTED_WIDTH = {EXPECTED_WIDTH}
EXPECTED_HEIGHT = {EXPECTED_HEIGHT}
WIDTH_OFFSET = {WIDTH_OFFSET}
HEIGHT_OFFSET = {HEIGHT_OFFSET}
HEADER_SIZE = 73
PIXELS = EXPECTED_WIDTH * EXPECTED_HEIGHT
SECONDS = {seconds}
MAX_PACKETS = {max_packets}
CHECKSUM_OFFSET = 0
SEQ_OFFSET = 2
START_PIXEL_OFFSET = 4
PIXEL_NUMBER_OFFSET = 8
TIMESTAMP_SECONDS_OFFSET = 10
TIMESTAMP_NANOSECONDS_OFFSET = 14
FRAME_RATE_OFFSET = 22
VERSION_OFFSET = 24
EXPECTED_START_PIXEL = 0
EXPECTED_PIXEL_NUMBER = PIXELS
EXPECTED_FRAME_RATE = 30


def median_value(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def percentile_value(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    return float(ordered[idx])


def depth_bin(depth):
    if depth <= 2:
        return "sentinel_le2"
    if depth < 500:
        return "0003_0499"
    if depth < 1000:
        return "0500_0999"
    if depth < 2000:
        return "1000_1999"
    if depth < 3000:
        return "2000_2999"
    if depth < 4000:
        return "3000_3999"
    if depth <= 5000:
        return "4000_5000"
    if depth <= 8000:
        return "5001_8000"
    return "gt8000"

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", PORT))
s.settimeout(1.0)

count = 0
good_size = 0
good_header = 0
good_pixel_number = 0
good_start_pixel = 0
good_frame_rate = 0
sizes = {{}}
first_addr = None
first_packet = None
first_header = None
first_depth_layout = None
validish = 0
all_2mm = 0
valid_non_sentinel_packets = 0
valid_pixels_total = 0
range_2000_5000_pixels_total = 0
range_2000_5000_majority_packets = 0
range_2000_5000_median_packets = 0
center_roi_valid_total = 0
center_roi_2000_5000_total = 0
center_roi_2000_5000_majority_packets = 0
bin_counts_total = Counter()
near_any_lt_1000_packets = 0
near_majority_lt_1000_packets = 0
near_median_lt_1000_packets = 0
sentinel_2mm_pixels_total = 0
negative_depth_pixels_total = 0
seq_gap_count = 0
timestamp_backward_count = 0
prev_seq_u16 = None
prev_timestamp = None
seq_values = []
width_values = Counter()
height_values = Counter()
pixel_number_values = Counter()
start_pixel_values = Counter()
frame_rate_values = Counter()
version_values = Counter()
depth_summaries = []
started = time.time()

while time.time() - started < SECONDS and count < MAX_PACKETS:
    try:
        data, addr = s.recvfrom(65535)
    except socket.timeout:
        continue
    count += 1
    first_addr = first_addr or addr
    first_packet = first_packet or data
    sizes[len(data)] = sizes.get(len(data), 0) + 1
    if len(data) == EXPECTED_SIZE:
        good_size += 1
    if len(data) >= HEADER_SIZE:
        check_sum = struct.unpack_from("<h", data, CHECKSUM_OFFSET)[0]
        seq_num = struct.unpack_from("<h", data, SEQ_OFFSET)[0]
        seq_u16 = seq_num & 0xFFFF
        start_pixel = struct.unpack_from("<I", data, START_PIXEL_OFFSET)[0]
        pixel_number = struct.unpack_from("<h", data, PIXEL_NUMBER_OFFSET)[0]
        timestamp_seconds = struct.unpack_from("<I", data, TIMESTAMP_SECONDS_OFFSET)[0]
        timestamp_nanoseconds = struct.unpack_from("<I", data, TIMESTAMP_NANOSECONDS_OFFSET)[0]
        width = struct.unpack_from("<h", data, WIDTH_OFFSET)[0]
        height = struct.unpack_from("<h", data, HEIGHT_OFFSET)[0]
        frame_rate = struct.unpack_from("<h", data, FRAME_RATE_OFFSET)[0]
        version = data[VERSION_OFFSET]
        first_header = first_header or (
            check_sum,
            seq_num,
            start_pixel,
            pixel_number,
            timestamp_seconds,
            timestamp_nanoseconds,
            width,
            height,
            frame_rate,
            version,
        )
        seq_values.append(seq_u16)
        width_values[width] += 1
        height_values[height] += 1
        pixel_number_values[pixel_number] += 1
        start_pixel_values[start_pixel] += 1
        frame_rate_values[frame_rate] += 1
        version_values[version] += 1
        if prev_seq_u16 is not None and ((prev_seq_u16 + 1) & 0xFFFF) != seq_u16:
            seq_gap_count += 1
        prev_seq_u16 = seq_u16
        timestamp = (timestamp_seconds, timestamp_nanoseconds)
        if prev_timestamp is not None and timestamp < prev_timestamp:
            timestamp_backward_count += 1
        prev_timestamp = timestamp
        if width == EXPECTED_WIDTH and height == EXPECTED_HEIGHT:
            good_header += 1
        if pixel_number == EXPECTED_PIXEL_NUMBER:
            good_pixel_number += 1
        if start_pixel == EXPECTED_START_PIXEL:
            good_start_pixel += 1
        if frame_rate == EXPECTED_FRAME_RATE:
            good_frame_rate += 1
    if len(data) == EXPECTED_SIZE:
        depths = []
        unsigned_depths = []
        confs = []
        for i in range(PIXELS):
            off = HEADER_SIZE + i * 4
            depth_signed = struct.unpack_from("<h", data, off)[0]
            depths.append(depth_signed)
            unsigned_depths.append(struct.unpack_from("<H", data, off)[0])
            confs.append(data[off + 2])
        unique_depths = len(set(depths))
        depth_min = min(depths)
        depth_max = max(depths)
        depth_mean = sum(depths) / len(depths)
        conf_counts = Counter(confs)
        sentinel_2mm_pixels = sum(1 for depth in depths if depth == 2)
        negative_depth_pixels = sum(1 for depth in depths if depth < 0)
        valid_non_sentinel = [depth for depth in depths if depth > 2]
        valid_count = len(valid_non_sentinel)
        valid_median = median_value(valid_non_sentinel)
        valid_p25 = percentile_value(valid_non_sentinel, 0.25)
        valid_p75 = percentile_value(valid_non_sentinel, 0.75)
        valid_lt1000 = sum(1 for depth in valid_non_sentinel if depth < 1000)
        valid_2000_5000 = sum(1 for depth in valid_non_sentinel if 2000 <= depth <= 5000)
        for depth in depths:
            bin_counts_total[depth_bin(depth)] += 1
        center_roi_depths = []
        for row in range(10, 20):
            for col in range(13, 27):
                center_roi_depths.append(depths[row * EXPECTED_WIDTH + col])
        center_roi_valid = [depth for depth in center_roi_depths if depth > 2]
        center_roi_2000_5000 = sum(1 for depth in center_roi_valid if 2000 <= depth <= 5000)
        center_depth = depths[(EXPECTED_HEIGHT // 2) * EXPECTED_WIDTH + (EXPECTED_WIDTH // 2)]
        sentinel_2mm_pixels_total += sentinel_2mm_pixels
        negative_depth_pixels_total += negative_depth_pixels
        valid_pixels_total += valid_count
        range_2000_5000_pixels_total += valid_2000_5000
        center_roi_valid_total += len(center_roi_valid)
        center_roi_2000_5000_total += center_roi_2000_5000
        if unique_depths == 1 and depth_min == 2:
            all_2mm += 1
        if depth_max > 100 or unique_depths > 10:
            validish += 1
        if valid_count:
            valid_non_sentinel_packets += 1
            if valid_2000_5000 * 2 >= valid_count:
                range_2000_5000_majority_packets += 1
            if valid_median is not None and 2000 <= valid_median <= 5000:
                range_2000_5000_median_packets += 1
            if center_roi_valid and center_roi_2000_5000 * 2 >= len(center_roi_valid):
                center_roi_2000_5000_majority_packets += 1
            if valid_lt1000:
                near_any_lt_1000_packets += 1
            if valid_lt1000 * 2 >= valid_count:
                near_majority_lt_1000_packets += 1
            if valid_median is not None and valid_median < 1000:
                near_median_lt_1000_packets += 1
        if len(depth_summaries) < 20:
            depth_summaries.append((
                count,
                depth_min,
                depth_max,
                depth_mean,
                unique_depths,
                valid_count,
                valid_median,
                valid_p25,
                valid_p75,
                valid_lt1000,
                valid_2000_5000,
                len(center_roi_valid),
                center_roi_2000_5000,
                center_depth,
                min(unsigned_depths),
                max(unsigned_depths),
                conf_counts.most_common(3),
            ))
        if first_depth_layout is None:
            valid_coords = [
                (i // EXPECTED_WIDTH, i % EXPECTED_WIDTH, depth)
                for i, depth in enumerate(depths)
                if depth > 2
            ]
            row_counts = Counter(row for row, _col, _depth in valid_coords)
            col_counts = Counter(col for _row, col, _depth in valid_coords)
            first_depth_layout = (
                len(valid_coords),
                row_counts.most_common(),
                col_counts.most_common(12),
                valid_coords[:80],
            )

s.close()

print(f"DTOF_UDP_PORT={{PORT}}")
print(f"PACKETS={{count}}")
print(f"GOOD_SIZE_4873={{good_size}}")
print(f"GOOD_HEADER_40x30={{good_header}}")
print(f"GOOD_PIXEL_NUMBER_1200={{good_pixel_number}}")
print(f"GOOD_START_PIXEL_0={{good_start_pixel}}")
print(f"GOOD_FRAME_RATE_30={{good_frame_rate}}")
print(f"VALIDISH_DEPTH_PACKETS={{validish}}")
print(f"ALL_2MM_PACKETS={{all_2mm}}")
print(f"VALID_NON_SENTINEL_PACKETS={{valid_non_sentinel_packets}}")
print(f"VALID_PIXELS_TOTAL={{valid_pixels_total}}")
print(f"RANGE_2000_5000_PIXELS_TOTAL={{range_2000_5000_pixels_total}}")
if valid_pixels_total:
    print(f"RANGE_2000_5000_PIXEL_RATIO={{range_2000_5000_pixels_total / valid_pixels_total:.6f}}")
else:
    print("RANGE_2000_5000_PIXEL_RATIO=nan")
print(f"RANGE_2000_5000_MAJORITY_PACKETS={{range_2000_5000_majority_packets}}")
print(f"RANGE_2000_5000_MEDIAN_PACKETS={{range_2000_5000_median_packets}}")
print(f"CENTER_ROI_VALID_TOTAL={{center_roi_valid_total}}")
print(f"CENTER_ROI_2000_5000_TOTAL={{center_roi_2000_5000_total}}")
if center_roi_valid_total:
    print(f"CENTER_ROI_2000_5000_RATIO={{center_roi_2000_5000_total / center_roi_valid_total:.6f}}")
else:
    print("CENTER_ROI_2000_5000_RATIO=nan")
print(f"CENTER_ROI_2000_5000_MAJORITY_PACKETS={{center_roi_2000_5000_majority_packets}}")
print(f"NEAR_ANY_LT_1000_PACKETS={{near_any_lt_1000_packets}}")
print(f"NEAR_MAJORITY_LT_1000_PACKETS={{near_majority_lt_1000_packets}}")
print(f"NEAR_MEDIAN_LT_1000_PACKETS={{near_median_lt_1000_packets}}")
print(f"SENTINEL_2MM_PIXELS_TOTAL={{sentinel_2mm_pixels_total}}")
print(f"NEGATIVE_DEPTH_PIXELS_TOTAL={{negative_depth_pixels_total}}")
print(f"SEQ_GAP_COUNT={{seq_gap_count}}")
print(f"TIMESTAMP_BACKWARD_COUNT={{timestamp_backward_count}}")
if seq_values:
    print(f"SEQ_MIN={{min(seq_values)}}")
    print(f"SEQ_MAX={{max(seq_values)}}")
print("SIZES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(sizes.items())))
print("WIDTH_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(width_values.items())))
print("HEIGHT_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(height_values.items())))
print("PIXEL_NUMBER_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(pixel_number_values.items())))
print("START_PIXEL_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(start_pixel_values.items())))
print("FRAME_RATE_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(frame_rate_values.items())))
print("VERSION_VALUES=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(version_values.items())))
print("DEPTH_BINS_TOTAL=" + ",".join(f"{{k}}:{{v}}" for k, v in sorted(bin_counts_total.items())))
for seq, depth_min, depth_max, depth_mean, unique_depths, valid_count, valid_median, valid_p25, valid_p75, valid_lt1000, valid_2000_5000, center_roi_valid, center_roi_2000_5000, center_depth, unsigned_min, unsigned_max, conf_top in depth_summaries:
    valid_median_text = "nan" if valid_median is None else f"{{valid_median:.1f}}"
    valid_p25_text = "nan" if valid_p25 is None else f"{{valid_p25:.1f}}"
    valid_p75_text = "nan" if valid_p75 is None else f"{{valid_p75:.1f}}"
    print(
        f"DEPTH_SUMMARY seq={{seq}} min={{depth_min}} max={{depth_max}} mean={{depth_mean:.1f}} "
        f"unique={{unique_depths}} valid={{valid_count}} valid_median={{valid_median_text}} "
        f"valid_p25={{valid_p25_text}} valid_p75={{valid_p75_text}} "
        f"valid_lt1000={{valid_lt1000}} valid_2000_5000={{valid_2000_5000}} "
        f"center_roi_valid={{center_roi_valid}} center_roi_2000_5000={{center_roi_2000_5000}} "
        f"center={{center_depth}} unsigned_min={{unsigned_min}} "
        f"unsigned_max={{unsigned_max}} conf_top={{conf_top}}"
    )
if first_depth_layout:
    valid_count, row_counts, col_counts, valid_coords = first_depth_layout
    print(f"FIRST_VALID_COORD_COUNT={{valid_count}}")
    print("FIRST_VALID_ROW_COUNTS=" + ",".join(f"{{row}}:{{count}}" for row, count in row_counts))
    print("FIRST_VALID_COL_COUNTS_TOP=" + ",".join(f"{{col}}:{{count}}" for col, count in col_counts))
    print("FIRST_VALID_COORDS=" + ";".join(f"{{row}}:{{col}}:{{depth}}" for row, col, depth in valid_coords))
if first_addr:
    print(f"FIRST_ADDR={{first_addr[0]}}:{{first_addr[1]}}")
if first_packet:
    print("FIRST_32_HEX=" + first_packet[:32].hex())
if first_header:
    (
        check_sum,
        seq_num,
        start_pixel,
        pixel_number,
        timestamp_seconds,
        timestamp_nanoseconds,
        width,
        height,
        frame_rate,
        version,
    ) = first_header
    print(
        "FIRST_HEADER="
        + f"checksum={{check_sum}} seq={{seq_num}} start={{start_pixel}} pixelNumber={{pixel_number}} "
        + f"timestamp={{timestamp_seconds}}.{{timestamp_nanoseconds}} width={{width}} height={{height}} "
        + f"frameRate={{frame_rate}} version={{version}}"
    )

if count and good_size and good_header:
    print("DTOF_UDP_CHECK=PASS")
else:
    print("DTOF_UDP_CHECK=FAIL")
if (
    count
    and good_size == count
    and good_header == count
    and good_pixel_number == count
    and good_start_pixel == count
    and good_frame_rate == count
):
    print("DTOF_UDP_STRICT_CHECK=PASS")
else:
    print("DTOF_UDP_STRICT_CHECK=FAIL")
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--max-packets", type=int, default=20)
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("paramiko is not installed. Use .venv\\Scripts\\python in this workspace.")
        return 2

    remote_script = textwrap.dedent(build_remote_script(args.seconds, args.max_packets))
    command = "python3 - <<'PY'\n" + remote_script + "\nPY"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=args.seconds + 10)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
    finally:
        client.close()

    if out:
        print(out, end="")
    if err:
        print(err, end="")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
