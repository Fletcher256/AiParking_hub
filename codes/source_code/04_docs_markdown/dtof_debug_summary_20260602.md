# dToF Debug Session Summary — 2026-06-02

Status: **dToF hardware proven healthy; sustained capture blocked by an SS928 VI raw-dump
quirk.** Stopped at user request to summarize. Perception-only throughout; no actuator /
MCU / CAN / chassis path was ever touched.

---

## 1. Bottom line

- The dToF module **works**: laser, SPAD, MIPI, VI, EEPROM/temperature, and the
  `DtofProcess` depth solver all function. With a single good frame it produces
  **339 valid real-depth pixels (median ≈ 5.5 m)** — i.e. genuine structured depth, not
  "all 2mm / dead module".
- The blocker is **not** format/parsing/ROS/calibration/500-vs-1000ps. It is a
  **steady-state frame-delivery quirk in the SS928 `BYPASS_BE` VI raw-dump path** on this
  board: the only frames that come out *populated* are the 1–2 frames flushed during a
  pipe-attribute *transition*; steady-state the dump returns empty buffers (or none).
- `2 mm` is the `DtofProcess` "no valid peak" output sentinel (confirmed in source).
- This single quirk **explains every prior "tried, ineffective" experiment**
  (RAW10/NONE, RAW12/NONE, KEEPATTR, UNPACK10, bitwidth, force500, pwm5, FE_OUT/BAS):
  they all hit the same wall, so that effort was not wasted reasoning — it was circling a
  real SDK-level limitation.

---

## 2. The exact finding (live evidence, this session)

Module was moved by the user from J4 back to **J3 / dtof0 / sensor2 / i2c4** during this
session. Behavior is the same on both ports; it is **not** port-specific.

dToF on J3, official decode (`sample_dtof_official_dbg 1`):
- frames 1–2: pipe still `pixfmt=21 compress=4` (RAW12+LINE), `raw_max=1023`,
  `raw_nonzero≈76526` (full histogram) → VM saw **valid=339/346 pixels, median ≈5.5 m**.
- frame 3…630: pipe became `pixfmt=20 compress=0` (RAW10+NONE), `raw_nonzero=0` →
  output all 2 mm. Frames keep being delivered, but **empty**.
- `temp=26.20 °C` (frame ≥60) → EEPROM/i2c5(+i2c4) and temperature read are fine.

Dump-path behavior matrix (observed across builds):

| dump pipe state | `ss_mpi_vi_get_pipe_frame` | buffer content |
|---|---|---|
| **10BPP + NONE** (official `vi_bayerdump` switch) | continuous delivery | **empty** in steady state |
| 12BPP + LINE (KEEP_PIPE_ATTR) | **`frame err`** (timeout) | — |
| 12BPP + NONE (compress dropped, bit-width kept) | **`frame err`** (timeout) | — |

Interpretation: the populated buffers exist only as RAW12+LINE, but the dump API only
*delivers* frames when the pipe is RAW10+NONE, and in that steady state the front-end no
longer fills them. The 2 good frames are the RAW12+LINE buffers flushed mid-transition.
There is no single pipe state that both delivers AND is populated, via this BYPASS_BE
dump path, on this hardware/SDK build.

Evidence (board stdout captured in session logs under `logs/`; VM UDP via
`tools/vm_dtof_udp_check.py`):
- clean `official_dbg` J3: seq1 `valid=339 median=5550mm`, seq2 `valid=346 median=5456mm`,
  seq3-200 all-2mm.
- `unpack10_keepattr` and `raw12none_unpack10`: `Linear:get vi_pipe 1 frame err!` (no frames).

---

## 3. Root-cause source references

- `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/dtof_dumpraw.c`
  - `set_dump_pipe_attr()` (≈L334): enables frame dump, and (unless `DTOF_KEEP_PIPE_ATTR`)
    forces `pixel_format=BAYER_10BPP`, `compress=NONE`.
  - `dump_process()` (≈L619): `ss_mpi_vi_get_pipe_frame(..., 4000ms)`; prints
    `Linear:get vi_pipe N frame err!` on timeout.
  - `2 mm` originates from `DtofProcess` output (`out_eq_2` counter).
- `sample_dtof.c` `sample_dtof_get_one_dtof_sensor_vi_cfg()`: dtof pipe is `BYPASS_BE`;
  case1→sensor2/dev2/pipe1 (J3), case2→sensor3/dev3/pipe1 (J4).
- Default VB raw pool & pipe = `RAW12BPP + COMPRESS_LINE`; GS1860 MIPI is 10-bit/1lane
  (`open_camera .../sample_comm_vi.c` `g_mipi_1lane_chn0_sensor_gs1860_10bit_1m_nowdr_attr`).

---

## 4. Builds produced this session (all on the VM, deployed to board)

VM build dir: `/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof`
Toolchain: `/opt/linux/x86-arm/aarch64-mix210-linux/bin` (add to PATH; `/etc/profile`
does it for interactive shells only). Build: `make EXTRA_CFLAGS='...'`.

| board binary | macros / edit | result |
|---|---|---|
| `sample_dtof_unpack10_keepattr` (was a245…, then 7c2ef7c4) | `-DDTOF_FORCE_UNPACK_10BIT -DDTOF_KEEP_PIPE_ATTR`, pristine source | `frame err` (no frames) |
| `sample_dtof_raw12none_unpack10` (2f96209f) | `-DDTOF_FORCE_UNPACK_10BIT`; `dtof_dumpraw.c` `set_dump_pipe_attr` pixel_format line removed (compress=NONE, keep 12bpp) | `frame err` (no frames) |

Pre-existing reference binary that gives the 2 good transition frames:
`sample_dtof_official_dbg` (d4a66b1c) = official + `FORCE_UNPACK_10BIT` (does the 10/NONE
switch).

---

## 5. State left on board / VM (all reversible, backed up)

Board `/opt/sample/official_dtof/`:
- **Clean baseline `sample_dtof` (SHA 4aaa07c8…) — UNTOUCHED.**
- Added experiment binaries: `sample_dtof_unpack10_keepattr`, `sample_dtof_raw12none_unpack10`.
- No process left running; no UDP/RTSP listener; media stack loaded (boot autorun).

VM `/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/`:
- `sample_dtof.c` = pristine vendor **+ one line disabled**: `rtsp_set_client_event_cb(...)`
  (the VM's older `libxoprtsp.a` lacks that symbol; case1/2 don't use RTSP).
- `dtof_dumpraw.c` = pristine vendor **+ one line removed**: `pipe_attr.pixel_format = pixel_format;`
- Backups: `sample_dtof.c.bak_polluted_*`, `dtof_dumpraw.c.bak_polluted_*`,
  `dtof_dumpraw.c.bak_pre12none`, plus `sample_dtof.prevbuild`.
- **To restore fully pristine** (recommended before any future clean build): re-upload
  `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/{sample_dtof.c,dtof_dumpraw.c}`
  via `tools/vm_ssh_run.py put-text`.

Hardware: dToF FPC currently on **J3**. Serial **COM11 not connected** to the PC (only
network/SSH was used).

---

## 6. Ways forward (ranked recommendation)

> **2026-06-02 update:** USB/serial path is **RULED OUT** — the user confirmed this dToF
> module has no USB port / serial debug-board accessible to the PC. The link must therefore
> come through the SS928 MIPI path. Re-ranked accordingly.

0. ~~Module's own USB/serial output path~~ — **not available** (no USB/serial connector).
   (Per official docs the module's onboard GK7205 can emit finished point cloud over
   USB-RNDIS/UVC/UART, but that interface isn't exposed on this unit.)
1. **(Now recommended) open_camera `sample_vio`** (the other official HiEuler MIPI
   implementation). Its README states it runs GS1860 dToF distance and is viewable on a host
   tool, and `docs/dtof_rebuild_next.md` records it reaching `DtofInit`/distance output. It
   may configure VI/dump differently (pipe topology, non-`BYPASS_BE`) and deliver steady
   frames where the MPP `sample_dtof` does not. Build dtof-only (`SUPPORT_RGB 0`,
   `SUPPORT_DTOF 1`) to avoid the known RGB/ISP kernel panic. Pure software; separate build.
2. **Grind the SS928 `sample_dtof` dump path.** Highest-value untried angle: set
   **RAW10+NONE at pipe *creation*** (consistent front-end+pipe from t=0, no mid-stream
   `vi_bayerdump` switch) — the prior "raw10_start" attempt that "failed" was on the
   *polluted* source (clk=0/rst=2/pipe=2); a **clean-source** retry is materially different.
   Other angles: larger VB raw pool / dump depth; non-`BYPASS_BE`; or a deliberate periodic
   pipe-attr re-toggle to keep flushing the populated transition frames (~low-Hz valid
   stream — hacky but exploits the one thing demonstrably working).

Note: even once steady delivery is achieved, **near-field accuracy is a separate question**
(the 339 valid pixels were median ≈5.5 m, far-biased). Resolve delivery first, then test a
30–80 cm object and, if needed, `dtof.ini` `configSwitchFlag`/`TimeFilter`/connected-domain
tuning.

---

## 7. Reproduce the key measurement

```powershell
# Board (SSH; serial COM11 is down). PYTHONIOENCODING=utf-8 required for board_run.py.
$env:PYTHONIOENCODING='utf-8'
& ".venv\Scripts\python.exe" tools\board_run.py 'cd /opt/sample/official_dtof; ./dtof_init.sh; timeout 35 ./sample_dtof_official_dbg 1 192.168.137.100'
# VM, concurrently:
& ".venv\Scripts\python.exe" tools\vm_dtof_udp_check.py --seconds 40 --max-packets 200
# Expect: seq1-2 valid≈339 median≈5.5m, then all-2mm  (= the dump quirk).
```
---

## 8. Continuation prep: clean RAW10/NONE-at-creation experiment

This continuation first re-read this summary and
`docs/dtof_j4_codex_plan_20260602.md`, then prepared route 2 without touching the board
or VM runtime state.

Local-only change:

- Added `tools/vm_build_official_raw10_create_clean.sh`.
- Added `docs/dtof_raw10_create_clean_runbook_20260602.md` as the approval/run sequence
  for build, deploy, steady-state capture, and near-distance validation.

Experiment intent:

- Build from a fresh SDK zip extraction, not from the currently polluted VM source tree.
- Disable only the VM-incompatible `rtsp_set_client_event_cb(...)` call inside the throwaway
  build directory.
- Compile with:
  `-DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN`.
- Keep the pipe in `RAW10 + NONE` from creation and avoid the later `vi_bayerdump()`
  runtime pipe-attribute transition by using `DTOF_KEEP_PIPE_ATTR`.
- Explicitly set `pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10` in the GS1860 pipe blocks,
  closing the previously noted gap where the raw10 startup macro changed pixel/compress
  but left `bit_width` at the common default.
- Emit and verify the marker string `DTOF_RAW10_CREATE_CLEAN` in the built binary.
- Produce a new non-overwriting binary name:
  `sample_dtof_raw10_create_clean`.

Local validation:

```text
raw10_pipe_blocks 2
rtsp_line True
sample_marker True
sample_get_char_anchor True
one_dtof_anchor_count 1
makefile_extra_hook True
makefile_marker True
```

No board/VM state-changing command was executed for this prep step.

Pending state-changing commands, requiring explicit user approval before running:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"

.venv\Scripts\python tools\vm_ssh_run.py --timeout 120 run "sshpass -p ebaina scp -p -o StrictHostKeyChecking=no <BINARY_FROM_BUILD_OUTPUT> root@192.168.137.2:/opt/sample/official_dtof/sample_dtof_raw10_create_clean"

.venv\Scripts\python tools\board_run.py "cd /opt/sample/official_dtof && sha256sum sample_dtof_raw10_create_clean && ls -l sample_dtof_raw10_create_clean"

.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition steady_raw10_create_clean_j3 --binary sample_dtof_raw10_create_clean --case 1 --seconds 35 --max-packets 120
```

Purpose:

- Verify whether a clean-source GS1860 J3/case1 pipeline created as `RAW10 + NONE` from
  startup can deliver steady non-zero raw frames and usable UDP depth, instead of relying
  on the known broken mid-stream dump transition.

Risk:

- Upload/build/deploy commands change VM or board filesystem state.
- The final capture command starts only the board dToF perception sample and the VM UDP
  listener.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  STM32/chassis-control path is involved.

Read-only preflight before requesting approval:

```text
logs/dtof_live_preflight_raw10_create_clean_prep.json
logs/dtof_live_preflight_raw10_create_clean_prep_summary.txt
pass=True
issues=[]
warnings=["VM TCP 8765 is occupied, usually by the existing Foxglove bridge"]
board_unsafe_process_count=0
vm_unsafe_process_count=0
board_udp_2368_occupied=False
vm_udp_2368_occupied=False
```

---

## 9. 2026-06-02 RAW10/NONE-at-creation build attempt and script correction

Approved VM-only commands were run:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"
```

Safety status:

- VM upload changed only `/tmp/vm_build_official_raw10_create_clean.sh`.
- VM build created a throwaway build directory under `/home/ebaina/official_dtof_raw10_create_clean_*`.
- The board was not touched.
- No dToF sample was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  STM32/chassis-control path was started.

Observed failure:

```text
expected at least two RAW10 pipe blocks, found 0
```

Artifact:

```text
logs/vm_ssh_20260602_193208_5e01fe0e.log
```

Interpretation:

- The failure was in the local patch phase, before compilation.
- The original script assumed the clean SDK already contained local diagnostic
  `DTOF_FORCE_RAW10_NONE` pipe blocks. The fresh SDK zip does not contain those blocks.
- This did not invalidate the route2 hypothesis; it showed the script anchor was too
  specific to an already-modified source tree.

Current local script correction:

- `tools/vm_build_official_raw10_create_clean.sh` now patches clean official source
  directly.
- It changes the dToF VB raw pool helper to receive `sns_type`, then for
  `HISI_GS1860_MIPI_1M_30FPS_10BIT` sets raw VB allocation to
  `bit_width=OT_DATA_BIT_WIDTH_10`, `pixel_format=OT_PIXEL_FORMAT_RGB_BAYER_10BPP`,
  and `compress_mode=OT_COMPRESS_MODE_NONE`.
- It inserts the same GS1860 RAW10/NONE/bit_width override into both default VI pipe
  initialization functions in `src/common/sample_comm_vi.c`.
- It inserts the same override immediately after the two
  `OT_VI_PIPE_BYPASS_BE` assignments in
  `sample_dtof_get_one_dtof_sensor_vi_cfg()`.
- A read-only inspection of the failed VM build extraction showed that clean
  `dtof_dumpraw.c` did not contain `DTOF_KEEP_PIPE_ATTR` support:
  `logs/vm_ssh_20260602_193919_61c30d2b.log`.
- The script now injects an `#ifndef DTOF_KEEP_PIPE_ATTR` guard around the
  `ss_mpi_vi_set_pipe_attr()` block in `set_dump_pipe_attr()`. This is required for the
  route2 experiment; otherwise `-DDTOF_KEEP_PIPE_ATTR` would compile but have no effect,
  and `vi_bayerdump()` would still perform the known-bad runtime pipe-attribute switch.
- It keeps the VM-only `rtsp_set_client_event_cb(...)` disable, marker string, and
  `EXTRA_CFLAGS` hook.
- A read-only check of the failed VM extraction also showed that this clean source lacks
  the local `g_camera_venc_started` symbol:
  `logs/vm_ssh_20260602_194154_9e00e1a9.log` and
  `logs/vm_ssh_20260602_194215_af87b14a.log`. The script now anchors the marker string
  after the clean-source `g_sig_flag` declaration instead.

Pending state-changing commands now require a new explicit approval because the uploaded
script content has changed:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"
```

Expected patch marker after this correction:

```text
RAW10_CREATE_PATCH dtof_bypass_blocks=2 common_vi_blocks=2 dump_keepattr_blocks=1
```

Read-only anchor-count verification against the failed VM clean extraction:

```text
logs/vm_ssh_20260602_194330_fbf7f105.log  OT_VI_PIPE_BYPASS_BE count = 2
logs/vm_ssh_20260602_194330_e4b37874.log  one-dtof insert anchor count = 1
logs/vm_ssh_20260602_194330_48182827.log  dump pipe attr switch block count = 1
logs/vm_ssh_20260602_194330_099777c6.log  common VI RAW10 anchor count = 2
```

---

## 10. 2026-06-02 route1 open_camera read-only prep

Because route2 still awaits explicit VM build approval, a read-only source pass was done
for the alternate open_camera route.

Local source paths:

```text
vendor/HiEuler_open_camera_unzip/open_camera-master/README.md
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/readme.txt
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/Makefile
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/dtof_dumpraw.c
```

Read-only findings:

- README states `sample_vio` runs GS1860 dToF distance data and can be viewed by the host
  point-cloud tool.
- The source already contains the intended dtof-only recovery setting:
  `SUPPORT_RGB 0` and `SUPPORT_DTOF 1`, avoiding the known RGB/ISP crash path.
- For the current physical J3/dtof0 target, the likely route1 runtime argument is:
  `./sample_vio 1 192.168.137.100`.
- Reason: `sns_info[1].i2c_bus = 5`; the dtof-only code then uses
  `i2c_bus_num = i2c_num - 1`, selecting the `i2c4` GS1860 branch. That branch configures
  `vi_dev=2`, `vi_pipe=2`, `mipi_dev=2`, and lane `4`.
- This differs from the MPP `sample_dtof` J3/case1 path, which used pipe 1, so route1 is
  a meaningful topology change rather than another RAW format sweep.
- `dtof_dumpraw.c` in open_camera still performs a RAW10/NONE pipe-attr preparation step,
  so route1 is not guaranteed to fix the issue; its value is the different VI/MIPI
  topology and vendor bring-up sequence.

No route1 file was edited, no VM build was started, and nothing was deployed or run on the
board.

Additional route1 runbook:

```text
docs/dtof_open_camera_route1_runbook_20260602.md
```

VM read-only checks found existing route1 artifacts under
`/home/ebaina/Workspace/open_camera-master`:

```text
demo/sample_vio SHA256 b39d168757f2b0832b5bfa74b6820648af8e2c47973134adb0c6847e4ee5a0a5
demo/dtof.ini SHA256 b2a8f8ae4d9a9b907cecc29b38b1d711c4e936e330bd29f5d3bdfca36f50f45e
demo/gs1860_register.ini SHA256 10fb0ee852380a151ee727ca5970b1103dbfee173685462eee8e6c52e440395f
code/mipi_imx347/imx347.c SHA256 ecbe1b168e1ec509922419a3112a2aae3ffc9339dad9cf77061be109428cd8d5
code/mipi_imx347/dtof_dumpraw.c SHA256 13c00d1c4da7b8b5ed6aa5df6977f7ff08ba8324067152113c46cc0beae80694
```

## 12. 2026-06-02 Route2 RAW10_CREATE clean result

Route2 was executed with a clean VM build and board deployment.

Build:

```text
logs/vm_ssh_20260602_202803_aa91e64d.log
sample_dtof_raw10_create_clean
SHA256=10016ad372d92a5c3f8a835eb777c9d5a8cae82eccac79e4fa0fb10a895ab0be
```

Harness fix:

- `tools/run_dtof_phase1_condition.py` originally closed stdin, causing
  `sample_pause()` to return immediately.
- It now pipes a delayed newline so official samples stay alive for the requested
  capture window.

Non-debug run after the fix:

```text
logs/dtof_phase1_steady_raw10_create_clean_j3_holdstdin_20260602_203036_report.json
PACKETS=120
GOOD_SIZE_4873=120
ALL_2MM_PACKETS=120
VALID_NON_SENTINEL_PACKETS=0
```

Debug variant:

```text
logs/vm_ssh_20260602_203319_e87ab619.log
sample_dtof_raw10_create_clean_dbg
SHA256=3888faf6a28b37440bc9a16e90c8b9c50b9f31c05d06d8344aec34a3eaef000d
```

Debug result:

```text
logs/dtof_phase1_steady_raw10_create_clean_dbg_j3_20260602_203420_report.json
gate=raw_zero_from_start
pixfmt=20
compress=0
raw_nonzero.median=0
raw_max.median=0
out_eq_2.median=1200
ALL_2MM_PACKETS=120
```

Conclusion:

- Starting MPP case1/J3 as `RAW10 + NONE` from creation still yields zero raw rows from
  frame 1.
- The all-2mm output is expected from empty raw input and cannot be corrected in ROS.
- Continue with route1 open_camera dtof-only topology.

Board read-only checks found:

- no `/opt/sample/open_camera_dtof` directory yet;
- existing `sample_vio` binaries only under `/opt/sample/mipi_rx/*`, not the open_camera
  dToF demo directory;
- no running `sample_vio` or `sample_dtof` process;
- one attempted process-check command containing forbidden actuator words was blocked by
  the local safety gate and was not sent to the board.

`init_dtof_cfg.sh` writes a register through `bspmm` and toggles GPIO96; route1 therefore
needs a separate explicit approval before running that init script.

Local-only paired capture helper added:

```text
tools/capture_dtof_udp_pair.py
```

Purpose:

- Start VM `vm_dtof_udp_check.py` and a whitelisted board perception sample as one paired
  capture.
- Support route1 `sample_vio` under `/opt/sample/open_camera_dtof`.
- Keep command construction constrained: only `sample_vio` or `sample_dtof*`, only
  whitelisted board directories, and simple board-arg tokens.

Local validation:

```powershell
.venv\Scripts\python -m py_compile tools\capture_dtof_udp_pair.py
.venv\Scripts\python tools\capture_dtof_udp_pair.py --help
.venv\Scripts\python tools\capture_dtof_udp_pair.py --condition bad --binary mcu_bridge --preflight-only
```

Observed:

- syntax check passed;
- help printed normally;
- `mcu_bridge` was rejected with
  `Invalid argument: --binary must be sample_vio or a sample_dtof* file name without a path`.

Route1 helper read-only preflight validation:

```powershell
.venv\Scripts\python tools\capture_dtof_udp_pair.py --condition route1_preflight_only_check --board-cwd /opt/sample/open_camera_dtof --binary sample_vio --board-args 1 192.168.137.100 --seconds 35 --max-packets 120 --preflight-only
```

Artifacts:

```text
logs/dtof_udp_pair_route1_preflight_only_check_20260602_200245_commands.txt
logs/dtof_udp_pair_route1_preflight_only_check_20260602_200245_preflight.json
logs/dtof_udp_pair_route1_preflight_only_check_20260602_200245_preflight_summary.txt
logs/dtof_udp_pair_route1_preflight_only_check_20260602_200245_preflight_stdout.log
```

Observed:

```text
pass=True
issues=[]
warnings=["VM TCP 8765 is occupied, usually by the existing Foxglove bridge"]
board_unsafe_process_count=0
vm_unsafe_process_count=0
board_udp_2368_occupied=False
vm_udp_2368_occupied=False
PREFLIGHT_ONLY=1
Not starting VM UDP capture or board sample.
```

---

## 11. 2026-06-02 local dry-run patch checker

Local-only tool added:

```text
tools/dtof_raw10_create_clean_patch_check.py
```

Purpose:

- Read the clean SDK zip or an extracted SDK tree.
- Check the same anchors used by `tools/vm_build_official_raw10_create_clean.sh`.
- Simulate the patch in memory and verify the expected post-patch markers.
- Fail before any VM upload/build if the script would miss a clean-source anchor.
- This tool does not write the zip or source tree.

Validation command:

```powershell
.venv\Scripts\python tools\dtof_raw10_create_clean_patch_check.py vendor\SS928V100_dtof_build_source.zip
```

Observed output:

```text
DTOF_RAW10_CREATE_CLEAN_PATCH_CHECK=PASS
common_vi_blocks=2
dtof_bypass_blocks=2
dump_keepattr_already=False
dump_pipe_attr_blocks=1
makefile_extra_hook=False
makefile_marker=1
old_call=1
old_sig=1
one_dtof_anchor=1
patched_call=1
patched_common_gs1860_overrides=2
patched_dump_keepattr_blocks=1
patched_makefile_extra_hook=True
patched_marker=2
patched_marker_call=1
patched_sample_pipe_bitwidth10=2
patched_sample_vb_bitwidth10=1
patched_sig=1
sample_get_char=1
sample_marker=1
vb_raw_anchor=1
```

Interpretation:

- The local clean zip contains every anchor needed by the corrected route2 script.
- The in-memory simulated patch produces the expected GS1860 RAW10/NONE/bit-width,
  `DTOF_KEEP_PIPE_ATTR`, marker, and Makefile hook changes.
- The Makefile has no `EXTRA_CFLAGS` hook in the clean zip, so the script's hook insertion
  is still required and expected.
- The dry-run strengthens confidence that the next approved VM build will reach the real
  compile/link stage rather than failing in the patch phase.
