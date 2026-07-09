# clean RAW10/NONE-at-creation runbook - 2026-06-02

Scope: perception-only dToF bring-up for Euler Pi / SS928 + GS1860 on J3
(`dtof0`, `sensor2`, `i2c4`, case1). This runbook does not authorize execution by
itself; each state-changing command still requires explicit user approval.

## Current hypothesis

The dToF module and `DtofProcess` are proven healthy by the transition frames. The
remaining blocker is steady-state frame delivery through the SS928 `BYPASS_BE` raw-dump
path. This experiment tests whether creating the pipe as `RAW10 + NONE` from startup,
with `bit_width=10` and no later `vi_bayerdump()` pipe-attribute switch, can deliver
steady non-zero raw frames.

## Prepared local script

```text
tools/vm_build_official_raw10_create_clean.sh
```

The script:

- extracts a fresh VM SDK zip into a new build directory;
- patches only the throwaway build tree;
- disables the VM-incompatible `rtsp_set_client_event_cb(...)` call;
- patches clean official source directly; the fresh SDK does not already contain local
  `DTOF_FORCE_RAW10_NONE` pipe blocks;
- changes the GS1860 raw VB pool, both common VI pipe init paths, and both dToF
  `BYPASS_BE` helper blocks to `bit_width=OT_DATA_BIT_WIDTH_10`,
  `pixel_format=OT_PIXEL_FORMAT_RGB_BAYER_10BPP`, and
  `compress_mode=OT_COMPRESS_MODE_NONE`;
- injects `DTOF_KEEP_PIPE_ATTR` support into clean `dtof_dumpraw.c` by guarding the
  `ss_mpi_vi_set_pipe_attr()` block in `set_dump_pipe_attr()`;
- compiles with
  `-DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN`;
- emits marker `DTOF_RAW10_CREATE_CLEAN`;
- outputs a new binary named `sample_dtof_raw10_create_clean`.

## Step A - VM upload and build

Requires approval because it changes VM `/tmp` and creates a VM build directory.

Local read-only precheck, no approval required:

```powershell
.venv\Scripts\python tools\dtof_raw10_create_clean_patch_check.py vendor\SS928V100_dtof_build_source.zip
```

Expected:

```text
DTOF_RAW10_CREATE_CLEAN_PATCH_CHECK=PASS
dtof_bypass_blocks=2
common_vi_blocks=2
dump_pipe_attr_blocks=1
one_dtof_anchor=1
patched_sample_pipe_bitwidth10=2
patched_sample_vb_bitwidth10=1
patched_common_gs1860_overrides=2
patched_dump_keepattr_blocks=1
patched_makefile_extra_hook=True
```

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh
```

Purpose: upload the prepared build script to the VM.

Risk: changes one VM `/tmp` file. It does not touch the board, start dToF, or start any
actuator path.

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"
```

Purpose: build `sample_dtof_raw10_create_clean` from a fresh SDK zip extraction.

Risk: creates/updates a VM build directory and `/tmp` build logs. It does not touch the
board, start dToF, or start any actuator path.

Expected build output must include:

```text
RAW10_CREATE_PATCH dtof_bypass_blocks=2 common_vi_blocks=2 dump_keepattr_blocks=1
DTOF_RAW10_CREATE_CLEAN
BUILD_DIR=/home/ebaina/official_dtof_raw10_create_clean_...
BINARY=/home/ebaina/official_dtof_raw10_create_clean_.../src/dtof/sample_dtof_raw10_create_clean
EXTRA_CFLAGS=-DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN
```

Read-only anchor precheck against the failed VM clean extraction:

```text
OT_VI_PIPE_BYPASS_BE count = 2
one-dtof insert anchor count = 1
dump pipe attr switch block count = 1
common VI RAW10 anchor count = 2
```

Evidence:

```text
logs/vm_ssh_20260602_194330_fbf7f105.log
logs/vm_ssh_20260602_194330_e4b37874.log
logs/vm_ssh_20260602_194330_48182827.log
logs/vm_ssh_20260602_194330_099777c6.log
```

History note:

- The first approved VM build attempt failed before compilation with
  `expected at least two RAW10 pipe blocks, found 0`.
- Log: `logs/vm_ssh_20260602_193208_5e01fe0e.log`.
- Cause: the first script version looked for local diagnostic macro blocks that do not
  exist in the fresh SDK zip.
- Additional read-only check showed clean `dtof_dumpraw.c` also lacks
  `DTOF_KEEP_PIPE_ATTR`; log: `logs/vm_ssh_20260602_193919_61c30d2b.log`.
- Additional read-only check showed the clean `sample_dtof.c` does not contain the local
  `g_camera_venc_started` symbol. Logs:
  `logs/vm_ssh_20260602_194154_9e00e1a9.log` and
  `logs/vm_ssh_20260602_194215_af87b14a.log`.
- The current script has been corrected to patch clean official source directly and to
  inject working keep-attr support. The marker string is anchored after `g_sig_flag`.

## Step B - Board deployment

Requires separate approval because it writes a new board binary under
`/opt/sample/official_dtof`. Do not overwrite the clean baseline `sample_dtof`.

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 120 run "sshpass -p ebaina scp -p -o StrictHostKeyChecking=no <BINARY_FROM_STEP_A> root@192.168.137.2:/opt/sample/official_dtof/sample_dtof_raw10_create_clean"
```

Purpose: deploy the newly built binary to
`/opt/sample/official_dtof/sample_dtof_raw10_create_clean` while preserving the executable
bit from the VM build output.

Risk: changes one board file under the official dToF sample directory. It does not start
dToF or any actuator path. This command intentionally uses `scp -p` rather than the local
SFTP deploy helper, because the helper currently performs `chmod 755` internally.

Read-only verification after deployment:

```powershell
.venv\Scripts\python tools\board_run.py "cd /opt/sample/official_dtof && sha256sum sample_dtof_raw10_create_clean && ls -l sample_dtof_raw10_create_clean"
```

## Step C - J3/case1 steady-state capture

Requires separate approval because it starts the board dToF perception sample and VM UDP
listener. No physical near-object action is needed for this first gate.

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition steady_raw10_create_clean_j3 --binary sample_dtof_raw10_create_clean --case 1 --seconds 35 --max-packets 120
```

Purpose: test whether J3/case1 created as `RAW10 + NONE` from startup delivers steady
non-zero raw frames.

Risk: starts only the board dToF sample and VM UDP checker. It does not start MCU bridge,
CAN actuator, serial actuator, motor, steering, brake, throttle, or STM32/chassis control.

Pass gate:

- board debug frames after frame 3 have `pixfmt=20`, `compress=0`;
- steady-state `raw_nonzero` is greater than zero;
- VM receives official `4873 byte / 40x30 / UDP2368` packets;
- depth is not all `2mm`.

Fail gate:

- steady-state raw remains zero from startup or after the first frames;
- `get_pipe_frame` times out;
- UDP remains all or nearly all `2mm`.

## Step D - Near-distance gate

Run only after Step C proves steady non-zero raw. This requires a physical action:
ask the user to place a 30-80cm target in the dToF field of view and wait for completion.

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near_raw10_create_clean_j3 --binary sample_dtof_raw10_create_clean --case 1 --seconds 35 --max-packets 120
```

Pass gate:

- most valid distances are below 1m for the near target;
- output is not dominated by the `2mm` sentinel;
- VM packet shape remains official `4873 byte / 40x30`.

## Documentation

After each approved step, write:

- command and purpose;
- safety status;
- logs and SHA paths;
- pass/fail interpretation;
- next action.

Primary docs:

```text
docs/dtof_debug_summary_20260602.md
docs/dtof_j4_codex_plan_20260602.md
```

## 2026-06-02 execution result

VM clean build succeeded after fixing the marker check:

```text
logs/vm_ssh_20260602_202803_aa91e64d.log
BINARY=/home/ebaina/official_dtof_raw10_create_clean_20260602_202802/src/dtof/sample_dtof_raw10_create_clean
SHA256=10016ad372d92a5c3f8a835eb777c9d5a8cae82eccac79e4fa0fb10a895ab0be
EXTRA_CFLAGS=-DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN
```

The first live run exposed a test-harness issue: `timeout ./{binary}` closed stdin, so
`sample_get_char()` returned immediately. `tools/run_dtof_phase1_condition.py` was fixed
to pipe a delayed newline:

```sh
( sleep <seconds>; printf "\n" ) | timeout <seconds+10> ./sample_dtof... <case> <ip>
```

After the stdin fix, the non-debug binary still produced official UDP packets but all
depths were the `2mm` sentinel:

```text
logs/dtof_phase1_steady_raw10_create_clean_j3_holdstdin_20260602_203036_report.json
PACKETS=120
GOOD_SIZE_4873=120
ALL_2MM_PACKETS=120
VALID_NON_SENTINEL_PACKETS=0
```

A debug build was then made by combining the same clean RAW10_CREATE patch with
`artifacts/official_dtof_dumpraw_keepattr_debug.c`:

```text
logs/vm_ssh_20260602_203319_e87ab619.log
BINARY=/home/ebaina/official_dtof_raw10_create_clean_20260602_203318/src/dtof/sample_dtof_raw10_create_clean_dbg
SHA256=3888faf6a28b37440bc9a16e90c8b9c50b9f31c05d06d8344aec34a3eaef000d
```

The decisive debug run failed from the first frame:

```text
logs/dtof_phase1_steady_raw10_create_clean_dbg_j3_20260602_203420_report.json
gate=raw_zero_from_start
debug_frame_count=12
pixfmt=20
compress=0
raw_nonzero.median=0
raw_max.median=0
out_eq_2.median=1200
ALL_2MM_PACKETS=120
```

Interpretation:

- Creating the GS1860 path as `RAW10 + NONE` from startup does not produce useful steady
  raw on the current SS928/J3 topology.
- This reproduces the known failure without relying on a runtime `vi_bayerdump()` pipe
  switch: the delivered data rows are zero from frame 1.
- Do not proceed to the near-distance gate on this route; it cannot show a true near
  object while raw is zero.

Follow-up:

- Continue with route1 open_camera, whose value is a different VI/MIPI topology
  (`vi_pipe=2`, `mipi_dev=2`) rather than another RAW10/NONE tweak on MPP pipe 1.
