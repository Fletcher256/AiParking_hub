# dToF (J4/sensor3) + Camera Link — Diagnosis & Codex Execution Plan

Date: 2026-06-02
Author: live diagnosis over SSH (serial COM11 unavailable at diagnosis time)
Scope: perception-only. **No actuator / MCU bridge / CAN / serial-actuator / motor /
steering / brake / throttle is ever started.** STM32/chassis stays disconnected from
software control.

## 2026-06-02 02:20 addendum - current case2 evidence supersedes part of the TL;DR

The latest SSH runs on J4/case2 show a stricter current failure mode than the older
`board_auto_ssh_20260531_*` logs:

- `sample_dtof_official_dbg 2 192.168.137.100` starts with two populated frames
  (`pixfmt=21`, `compress=4`, `raw_nonzero=76518/76527`, `raw_max=1023`), then
  after `vi_bayerdump()` changes the pipe to `pixfmt=20`, `compress=0`, every later
  frame has `raw_nonzero=0`, `raw_max=0`, and the processed output is all 2 mm.
- VM UDP capture from the same run received 120 valid 4873-byte packets, but only
  the first two packets were valid-ish; the remaining 118 packets were all 2 mm.
- The clean official `sample_dtof 2` shows the same steady-state UDP symptom:
  120 packets received, first two packets non-constant, then 118 all-2mm packets.

Evidence:

- `logs/dtof_phase1_current_board_20260602_021106.log`
- `logs/dtof_phase1_current_vm_20260602_021054.log`
- `logs/dtof_phase1_current_report_20260602_021106.json` classifies this run as
  `pipe_attr_zero_after_switch`.
- `logs/dtof_case2_clean_current_board_20260602_021249.log`
- `logs/dtof_case2_clean_current_vm_20260602_021236.log`
- Diagnostic-only keepattr run:
  `logs/dtof_phase1_current_keepattr_diag_20260602_022024_board.log` and
  `logs/dtof_phase1_current_keepattr_diag_20260602_022024_vm.log`.
  This kept `pixfmt=21`, `compress=4` and raw stayed non-zero for all printed frames
  (`raw_nonzero` about 12400, `raw_max=4095`), but DtofProcess output was still almost
  entirely the 2 mm sentinel. This confirms two layers must be separated:
  (1) the official RAW10/NONE switch currently zeros the captured raw stream on J4;
  (2) keeping the original pipe attributes preserves a raw stream but does not by itself
  produce usable depth.
- `logs/dtof_phase1_current_keepattr_report_20260602_022024.json` classifies this
  diagnostic run as `raw_present_output_invalid`.

Local helpers added for repeatable Phase1 evidence:

- `tools/run_dtof_phase1_condition.py`: starts VM UDP capture and board case2 in one
  command, writes paired logs under `logs/`, and now generates the matching JSON report
  automatically unless `--no-report` is passed.
- `tools/dtof_phase1_log_report.py`: summarizes a paired board/VM log and classifies
  it as `pipe_attr_zero_after_switch`, `raw_present_output_invalid`, or
  `undetermined`. It also separates `first_two`, `after_first_two`,
  `before_raw_zero`, and `from_raw_zero` frame statistics so the useful early official
  frames are not hidden by the all-2mm steady-state failure.
- `tools/dtof_phase1_compare_reports.py`: compares multiple JSON reports and suggests
  the next route. Current reports produce
  `fix_or_bypass_official_pipe_attr_zeroing_first`, with evidence in
  `logs/dtof_phase1_current_compare_20260602.json`.
  The v2 compare report at `logs/dtof_phase1_current_compare_20260602_v2.json` confirms
  that the official run has `first_two_raw_nonzero_median=76522.5` but steady-state
  `raw_nonzero_median=0.0`, while keepattr has raw present but invalid output.
- `tools/dtof_phase1_suite_status.py`: local-only report bookkeeping. It finds the
  latest report for labels such as `clear_official`, `near30cm_official`, and
  `covered_official`, summarizes the early-frame and steady-state fields, and can call
  `dtof_phase1_compare_reports.py` automatically with `--compare-out`. It does not
  contact the board or VM.
- `tools/dtof_phase1_next_step.py`: local-only next-step helper. It checks which Phase1
  physical-condition reports are still missing and prints the next physical setup,
  exact capture command, purpose, and risk.

Source location for the current official zeroing symptom:

- `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/dtof_dumpraw.c`
  `set_dump_pipe_attr()` calls `ss_mpi_vi_set_pipe_attr()` and, unless
  `DTOF_KEEP_PIPE_ATTR` is defined, forces `pixel_format` from 10-bit dump setting
  and `compress_mode = OT_COMPRESS_MODE_NONE`.
- Current board logs show that this transition changes J4 from `pixfmt=21 compress=4`
  to `pixfmt=20 compress=0`, after which `raw_nonzero=0`. Therefore the next code-level
  investigation should focus on why J4/sensor3 cannot deliver non-zero raw data after
  that specific pipe-attribute change, while keeping `*_keepattr*` as diagnostic-only.
- `sample_comm_vi_get_default_pipe_info()` initializes the GS1860 path as
  `OT_PIXEL_FORMAT_RGB_BAYER_12BPP` plus `OT_COMPRESS_MODE_LINE`. `deal_frame_data()`
  only unpacks ordinary 8/10/12/14/16-bit raw rows and does not decode line-compressed
  Bayer data. Therefore a keepattr run can prove that bytes continue to arrive, but it
  cannot be treated as a valid `DtofProcess()` input path unless line-compress decoding
  is implemented or the VI path is made to output true uncompressed raw data.
- The vendor dToF learning material under `vendor/dtof_sensor_driver-master/doc/`
  states the GS1860 module is 30x40, FOV 60 x 46 degrees, range 0.1-10 m, and its UDP
  point-cloud test uses a 20 cm +/- 3 cm flat ranging board with a 30x40 display /
  center-region check. This confirms the user's 20-50 cm target should be measurable;
  the current failure is a software/config/data-path issue until proven otherwise.

Additional source cross-check from the local SDK:

- Numeric enums confirm the observed transition:
  `OT_PIXEL_FORMAT_RGB_BAYER_10BPP == 20`,
  `OT_PIXEL_FORMAT_RGB_BAYER_12BPP == 21`,
  `OT_COMPRESS_MODE_NONE == 0`, and `OT_COMPRESS_MODE_LINE == 4`.
  Thus the current log transition `pixfmt=21 compress=4` to `pixfmt=20 compress=0`
  is exactly `RAW12 + LINE` to `RAW10 + NONE`.
- `sample_comm_vi_get_default_pipe_info()` sets all normal sensors to
  `RAW12 + LINE` by default. `HISI_GS1860_MIPI_1M_30FPS_10BIT` is not specially
  overridden there even though `sample_comm_vi_get_size_by_sns_type()` sizes it as
  `2560 x 31`.
- `sample_dtof_get_one_dtof_sensor_vi_cfg()` switches GS1860 to bypass-BE and disables
  ISP, but only changes the pipe to `RAW10 + NONE` when a local diagnostic macro such as
  `DTOF_FORCE_RAW10_NONE` is compiled in. The clean official build therefore starts J4 as
  `RAW12 + LINE` and changes it only later inside `vi_bayerdump()`.
- Historical evidence says that neither simple workaround is sufficient by itself:
  `artifacts/dtof_yolo_validation/dtof_conditions/20260601_214855/close_obstacle_raw10none_vbfix.json`
  shows a `RAW10 + NONE` startup variant still producing all-2mm output under a close
  obstacle, while
  `artifacts/dtof_yolo_validation/dtof_conditions/20260601_212009/close_obstacle_after_reboot_keepattr.json`
  shows keepattr producing non-flat depth but still dominated by 4-5 m ranges.
  Do not repeat these as final-route experiments unless a new hypothesis changes exactly
  what is being measured.

Implication: before treating the user-visible near-field problem as only a
`dtof.ini` post-processing issue, the next diagnostic must also determine why the
official dump path becomes zero after the RAW10/NONE pipe-attribute switch on the
current J4 run. `*_keepattr*` binaries remain diagnostic-only tools: they may be used
to observe whether raw histograms change under near-object / fully-covered scenes,
but they must not be promoted to the production baseline unless this document is
updated with explicit evidence and rationale.

Current controlled route after this source pass:

1. Still run Phase1 with the clean official diagnostic binary under the three physical
   conditions. Even if steady-state frames zero out, frame 1-2 are still useful evidence
   because they are captured before the broken `RAW10 + NONE` transition dominates.
2. If every official run classifies as `pipe_attr_zero_after_switch`, do not tune
   `dtof.ini` yet; the transport into `DtofProcess()` is not trustworthy enough.
3. If frame 1-2 or a diagnostic keepattr run changes clearly between clear / 30 cm /
   covered scenes, then the module and optical path are responding and the remaining
   work is data-path plus post-processing.
4. If frame 1-2 and keepattr diagnostics do not change even with the lens fully covered,
   move to Phase5 physical checks before more software experiments.
5. A future software fix should be judged by steady-state official case2 evidence:
   non-zero raw after frame 3 and UDP depth that changes to mostly `<1 m` under a
   20-50 cm flat obstruction. A build that only produces non-flat far depth is not enough.

---

## 0. TL;DR — what is actually wrong

The dToF module is **not dead**, and the problem is **not** UDP/ROS/parsing, **not**
a missing official `.ko`, and **not** "all 2mm" on the official pipeline. Hard evidence
(board `_dbg` logs `logs/board_auto_ssh_20260531_*.log`) shows:

```
[DTOF_DBG] frame=1 raw_min=0 raw_max=1023 raw_nonzero=64458 \
           out_min=0 out_max=8147 out_nonzero=792 out_eq_2=436 out_mid=6386 \
           switch=0 config=0 temp=0.00
```

Decode (HEIGHT*WEIGHT*BIN_NUM = 30*40*64 = 76800 histogram cells; 1200 output pixels):

- `raw_max=1023`, `raw_nonzero≈64000/76800 (~84%)` → **raw histogram is fully
  populated**. VCSEL fires, SPADs integrate, MIPI/VI transport is intact.
- `out_nonzero≈792/1200`, `out_max≈8147 mm` → `DtofProcess` resolves the **far** scene
  (6–8 m). `out_eq_2≈436` pixels are the "no valid peak" sentinel (this is where the
  "2mm" comes from — it is a DtofProcess output, not a transport bug).
- `switch=0 config=0` on every frame → **no near/far switching**; sensor is **locked in
  1000 ps far mode**.

### Root-cause hypothesis (ranked)

1. **Locked in 1000 ps far mode.** `dtof.ini [ModeSwitch] configSwitchFlag=false`
   (this is the vendor default too), and `gs1860_register.ini [common]` already equals the
   `[1000ps]` register values. Dynamic near/far switching (`gs1860_500ps_config` /
   `gs1860_1000ps_config`, `dtof_dumpraw.c:708-719`) therefore never triggers. Near
   objects (<1 m) land in the lowest TDC bins and are poorly resolved / reported as far or
   as the 2 mm sentinel — exactly the reported symptom.
2. **The earlier "force500 → still all 2mm" result is probably a test artifact.** 500 ps
   mode max range ≈ 62 bins × ~7.5 cm ≈ 4.6 m. In an *unobstructed* ~5.5 m room, 500 ps
   sees nothing in range → everything reads invalid/2 mm. 500 ps was likely **never tested
   with a near target present**. This must be retested correctly.
3. **The single decisive measurement was never taken on J4:** raw-vs-output with a flat
   object physically held at ~30–80 cm. `docs/dtof_yolo_diagnostic_20260601.md` defines
   this exact test and lists it as *pending*.
4. **Secondary / to rule out:** EEPROM calibration + temperature compensation read over
   **I2C5** (`temperatureBypass=false`, calib via `gs1860_read_eeprom`, `dtof_dumpraw.c:776`).
   I2C5 has known timeout noise on this board. Bad calib/temp would bias depth. Also the
   ROS obstacle-block layer requires ≥16 support px and 20% per-zone ratio, which can
   suppress sparse near returns even if the raw layer is fine.

### Confirmed environment state (2026-06-02, via SSH)

- Board `192.168.137.2` SSH **up**; VM `192.168.137.100` SSH **up**; host NIC
  `192.168.137.1`; VMware VMnet8 `192.168.247.1` (Foxglove side `192.168.247.129`).
- **Serial COM11 is UNAVAILABLE** — no USB-serial adapter (CH34x/CP210x/FTDI) is
  enumerated on the PC (only Bluetooth COM ports). `board_serial.py` and every wrapper
  that calls it **cannot run** until the USB-serial console cable is reconnected. Use
  `tools/board_run.py` (SSH) instead.
- SS928 media stack **is loaded** (`ot_isp/ot_vi/ot_mipi_rx/ot_base/...`) via boot
  autorun `/etc/init.d/S90autorun` = `cd /opt/ko; ./load_ss928v100 -i`. Board idle: no
  `sample_dtof` running, no `:2368`/`:554` listener.
- Clean official binary present and intact:
  `/opt/sample/official_dtof/sample_dtof` SHA256 `4aaa07c8…d73e9f35` (matches known-good).
  It **natively supports J4** at runtime: `case 2 → sample_dtof_one_dtof_sensor(3,…)` =
  dtof1/sensor3/i2c5. No rebuild is needed to test J4.
- ~35 experiment binaries also present (kept as archive; do **not** use as baseline).
- Diagnostic binary present: `/opt/sample/official_dtof/sample_dtof_official_dbg`
  (SHA `d4a66b1c…`) — clean official + the `[DTOF_DBG]` prints used above.

### Official case map (from `sample_dtof.c` usage())

| case | meaning | binding |
|---|---|---|
| 0 | sensor0 only | OS08A20 4lane |
| 1 | dtof0 | sensor2 / J3 / i2c4 |
| **2** | **dtof1** | **sensor3 / J4 / i2c5** ← current physical port |
| 3 | sensor0 + dtof0 | J3 |
| **4** | **sensor0 + dtof1** | OS08A20 + sensor3/J4 (note: sensor0 *and* sensor3 both on i2c5) |
| 5 | dtof0 + dtof1 | — |
| 7 | sensor0 + dtof0 + rtsp | J3 |

---

## 1. Operating rules for Codex (read first, every session)

1. **Safety boundary is absolute.** Only perception/compile/deploy/log/ROS2/Foxglove.
   Never start MCU bridge, CAN, serial actuator, motor, steering, brake, throttle. Never
   touch STM32/chassis control.
2. **Approval protocol** (`AGENTS.md`): before any state-changing board/VM command (module
   load, config edit, file move, process kill, reboot, package install, network change),
   print the exact command + purpose + risk and get explicit user approval. `board_run.py`
   has **no** built-in safety gate — self-enforce.
3. **Physical actions require a STOP + wait.** Reconnecting serial, plugging/unplugging
   dToF, moving the sensor, swapping cables, and *placing the near-field test object* must
   be requested from the user; wait for their confirmation before continuing.
4. **Shell access:** prefer SSH `tools/board_run.py` (serial is down). Always set
   `PYTHONIOENCODING=utf-8` for it (board output contains non-UTF8 bytes). When passing
   commands through PowerShell, avoid double-quoted `grep -E "a|b"` alternations (the `|`
   leaks as a real pipe); use `grep -e a -e b`.
5. **Baseline discipline:** standardize on the clean `sample_dtof` (SHA `4aaa07c8…`) and the
   clean `sample_dtof_official_dbg` (SHA `d4a66b1c…`). Do not promote any `*_raw10*`,
   `*_raw12*`, `*_keepattr*`, `*_unpack10*`, `*_force*_pwm5*`, `*_feout*`, `*_bitwidth*`
   binary to mainline. Keep them as archive only.
6. **Every conclusion needs a log + a reproducible command.** Save board/VM output under
   `logs/`, write findings to `docs/`.

---

## 2. Phase 0 — Connection & clean-baseline confirmation (read-only)

Goal: confirm we can drive the board and that the clean binary/config are in place.

```powershell
# Board shell over SSH (serial COM11 is currently unavailable)
$env:PYTHONIOENCODING='utf-8'
& "D:\parking_board_agent\.venv\Scripts\python.exe" "D:\parking_board_agent\tools\board_run.py" `
  'sha256sum /opt/sample/official_dtof/sample_dtof /opt/sample/official_dtof/sample_dtof_official_dbg; echo ---; lsmod | grep -e ot_isp -e ot_vi -e ot_mipi_rx; echo ---; ps -ef | grep -i -e sample_dtof -e rtsp | grep -v grep'
```

Pass criteria: `sample_dtof` = `4aaa07c8…`, `sample_dtof_official_dbg` = `d4a66b1c…`,
media modules listed, no sample running.

Optional but recommended — verify the diagnostic binary is truly clean (no format-forcing):
```powershell
& "...python.exe" "...board_run.py" 'strings /opt/sample/official_dtof/sample_dtof_official_dbg | grep -i -e "force gs1860" -e raw10 -e keepattr -e unpack || echo CLEAN_NO_FORCE_STRINGS'
```

**Serial decision (ask the user):** if any boot-console / crash-recovery work is wanted,
ask the user to reconnect the board's USB-serial console cable and confirm COM11 appears.
Not required for the dToF measurements below.

---

## 3. Phase 1 — The decisive raw-vs-output test on J4 (THE key experiment)

This is the one measurement that has never been taken on J4 and that localizes the fault.
It compares the raw histogram and the resolved depth between **unobstructed** and a
**flat object at ~30–80 cm**, using the `_dbg` binary so we see `raw_nonzero` and
`out_*` directly.

Note: `_dbg` only prints stats for the first 12 frames (`dtof_dumpraw.c:507`). Each run
is short; capture the 12 `[DTOF_DBG]` lines plus the one-time `fx/fy/cx/cy/k1..` calib
line from `dtof_init`.

### 1a. Approved board command (dtof-only, J4, no media reload needed — modules already up)
Purpose: run official dtof1/J4 with debug stats, stream UDP to the VM.
Risk: starts a perception-only sample; no actuator path. Reversible (Ctrl-C / timeout).

```sh
cd /opt/sample/official_dtof
./dtof_init.sh
timeout 35 ./sample_dtof_official_dbg 2 192.168.137.100
echo DTOF_J4_DBG_RC=$?
```
Run it over SSH:
```powershell
$env:PYTHONIOENCODING='utf-8'
& "...python.exe" "...board_run.py" 'cd /opt/sample/official_dtof; ./dtof_init.sh; timeout 35 ./sample_dtof_official_dbg 2 192.168.137.100; echo DTOF_J4_DBG_RC=$?'
```
If VI fails to start (e.g. `get vi_pipe … frame err`), fall back to a full sensor reload
first (APPROVAL needed — this is `insmod`-class):
```sh
cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20
```

### 1b. VM UDP capture (run concurrently, read-only on VM)
```powershell
& "...python.exe" "...tools\vm_dtof_udp_check.py" --seconds 35 --max-packets 120
```
Expect `GOOD_SIZE_4873`, `GOOD_HEADER_40x30`, and depth summaries.

### 1c. Two physical conditions — **STOP and have the user set the scene each time**
- **Condition A — unobstructed:** ask user to clear the dToF field of view. Run 1a+1b.
  Save board log + VM output as `…_J4_unobstructed`.
- **Condition B — near object:** ask user to hold a flat, non-glossy object (book / hand /
  cardboard) ~30–80 cm directly in front of the dToF, centered. Wait for confirmation.
  Run 1a+1b. Save as `…_J4_near40cm`.

### 1d. Decision gate (drives all later phases)
Compare `[DTOF_DBG]` and the VM depth summaries between A and B:

- **G1 — near resolves:** in B, `out_mid` and many pixels drop to ~300–800 mm and VM valid
  median/p25 drop clearly, while `raw_nonzero` stays high. → **Raw dToF works.** The
  remaining issue is mode/visualization/threshold. Skip to Phase 4 (and optionally Phase 2
  to widen near coverage). The board hardware/firmware is fine.
- **G2 — near does NOT resolve, raw still healthy:** in B, `raw_nonzero` stays high
  (object clearly changes the raw histogram) but `out_*` stays far / `out_eq_2` stays high.
  → Algorithm is stuck in far mode / mis-picking echo. → Phase 2 (mode) is the fix path;
  also verify Phase 3 (calib).
- **G3 — raw collapses or saturates with the near object:** `raw_nonzero` drops sharply or
  pins at `raw_max=1023` everywhere. → near saturation / optical issue → Phase 2 (reduce
  shot count / duty) and Phase 5 (physical).
- **G4 — no UDP / VI errors even unobstructed on J4:** J4 binding/clock/reset problem (J3
  worked historically). → Phase 5 (physical: compare J3 vs J4, reset timing, reseat).

Record which gate fired in `docs/`.

### 1e. Preferred local helper workflow

For repeatable paired logs, prefer the local helper instead of manually opening two
terminals. Run once per physical condition:

```powershell
.venv\Scripts\python tools\dtof_phase1_next_step.py
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition clear_official --binary sample_dtof_official_dbg --seconds 35 --max-packets 120
.venv\Scripts\python tools\dtof_phase1_suite_status.py --labels clear_official near30cm_official covered_official --out logs\dtof_phase1_suite_status_latest.json --compare-out logs\dtof_phase1_suite_compare_latest.json
```

Use the same pattern for:

- `clear_official`
- `near30cm_official`
- `covered_official`
- optional diagnostic-only `*_keepattr_diag` with `--binary sample_dtof_official_keepattr_dbg`

Do not compare conditions by eye only. Compare the generated JSON fields:

- `classification.gate`
- `board.raw_nonzero`
- `board.raw_zero_first_frame`
- `board.out_max`, `board.out_mid`, `board.out_eq_2`
- `vm.kv.ALL_2MM_PACKETS`, `vm.kv.PACKETS`
- `vm.depth_max`, `vm.depth_unique`

---

## 4. Phase 2 — Near/far mode tests (config-level, no source edit first)

Only if G2/G3. Two independent, reversible experiments; run each in **both** scene
conditions (especially with the near object — do NOT judge 500 ps on an empty far room).

### 2.0 Local-only candidate set

Before any board-side `dtof.ini` edit, generate local candidates:

```powershell
.venv\Scripts\python tools\dtof_phase2_config_candidates.py --out-dir artifacts\dtof_phase2_config_candidates\latest
```

This creates `manifest.json`, `README.md`, a baseline copy, and ordered `dtof_*.ini`
candidates under `artifacts/dtof_phase2_config_candidates/latest/`. These files are not
deployed automatically. Use them only after Phase 1 proves that raw data changes with a
near target while `DtofProcess` / UDP output remains wrong.

Candidate order:

1. `01_modeswitch_only`: `ModeSwitch.configSwitchFlag=true`.
2. `02_modeswitch_low_time_weight`: mode switch plus `TimeFilter.weight=1.0`.
3. `03_modeswitch_no_time_filter`: mode switch plus `TimeFilter.timeFilterFlag=false`.
4. `04_modeswitch_relaxed_components`: mode switch plus relaxed DepthDomain thresholds.
5. `05_modeswitch_spatial_filters_off`: mode switch plus `DepthDomain` and
   `KillFlyingPixels` disabled for diagnosis.
6. `06_modeswitch_first_echo_probe`: mode switch plus `HistoProc.echoOrderType=0`.
7. `07_single_echo_probe`: mode switch plus single-echo probe.
8. `08_debug_logging_only`: `LogEvent.logEvent=1` if library-side logs are useful.

Each candidate must be tested one at a time with a board backup/restore step and the same
Phase 1 near-object measurement. A useful candidate must make close obstruction produce
mostly `<1 m` valid depth without breaking 4873-byte UDP shape or becoming dominated by
2 mm sentinels.

### 2a. Enable dynamic near/far switching (preferred — uses official mechanism)
Back up then edit `dtof.ini` `configSwitchFlag=false → true`. This is a config write →
APPROVAL + keep backup.
```sh
cd /opt/sample/official_dtof
cp dtof.ini dtof.ini.bak_$(date +%s)
sed -i 's/^configSwitchFlag=false/configSwitchFlag=true/' dtof.ini
grep configSwitchFlag dtof.ini
```
Run 1a+1b in both conditions. Watch for `------switch to 500ps------` /
`------switch to 1000ps-------` in the board log and `switch=`/`config=` changing in
`[DTOF_DBG]`. Expect: with the near object, it switches to 500 ps and near pixels resolve.
Restore from `.bak` afterward if it regresses far performance.

### 2b. Forced 500 ps **with a near object present** (corrects the earlier flawed test)
Use the existing clean+force binary; have the user hold the object at ~40 cm first.
```sh
cd /opt/sample/official_dtof
./dtof_init.sh
timeout 35 ./sample_dtof_official_force500_dbg 2 192.168.137.100
echo RC=$?
```
Expect near pixels ~300–800 mm. If 500 ps resolves near but 1000 ps doesn't, that confirms
hypothesis #1 and makes Phase 2a (auto-switch) the production fix.

Deliverable of Phase 2: the config (default-1000 + auto-switch, or a fixed mode) that makes
case 2 report **most valid distances < 1 m when occluded at close range** (acceptance).

---

## 5. Phase 3 — Calibration / EEPROM / temperature (rule-out)

Only if depth magnitude looks biased or G2 persists after mode fix.

- At `dtof_init`, the binary prints `fx,fy,cx,cy,k1,k2,p1,p2,k3`. Capture that line; sane
  values are non-zero and stable (compare J4 run vs a J3 run, case 1). All-zero/garbage ⇒
  EEPROM (i2c5 addr 0x50) read failing on J4.
- Temperature: `_dbg` shows `temp=0.00` only because temp is first sampled at frame 30
  (`dtof_dumpraw.c:674`) and `_dbg` stops printing at frame 12 — so `temp=0.00` in those
  logs is **expected, not a fault**. To check real temp, capture a longer run's UDP and
  confirm depth doesn't drift; if needed, build a variant that prints temp past frame 30.
- I2C5 is shared by sensor0 (camera) and sensor3 (dtof) per `sample_dtof.c`. Do **not** run
  generic `i2cdetect` (known timeout storm). If EEPROM read is suspect, compare against a
  J3/case-1 run where dtof is on i2c4.

Do **not** change ko/init reset logic unless G4 (Phase 5) indicates a J4 binding fault;
`dtof_init.sh` already resets both dtofs via GPIO96 and muxes pwm0_0/pwm0_5/gpio12_0.

---

## 6. Phase 4 — Only after case 2 is correct: ROS / obstacle blocks / camera / Foxglove

Gate: case 2 on J4 shows most valid distances < 1 m under close occlusion (acceptance).

1. Re-evaluate the obstacle-block thresholds against the fresh near captures. Current rule
   (per `docs/dtof_yolo_diagnostic_20260601.md`): ≥16 support px and 20% per-zone ratio,
   support `<500 mm` ≈ 10/1200 unobstructed. Tune so a real 30–80 cm object trips a block
   without unobstructed false positives. Use
   `tools/dtof_yolo_validation.py capture-dtof` / `compare-dtof`.
2. **case 4 (sensor0 + dtof1)** caution: sensor0 and sensor3 **share i2c5** → bus
   contention is plausible. Validate dtof still ranges correctly with the camera up; if it
   regresses only in case 4, that is the i2c5-sharing issue, not the dtof itself.
3. Restore RTSP + ROS2 + Foxglove via the documented managers
   (`tools/perception_link_manager.py`, `tools/foxglove_bridge_control.py`). Confirm
   Foxglove panels: `/parking/camera/image_jpeg`, `/parking/dtof/depth_color`,
   `/parking/dtof/obstacle_view`, `/parking/sensors/health` at `ws://192.168.247.129:8765`.

---

## 7. Phase 5 — Physical (only if G3/G4, requires user)

Ask the user (STOP + wait) to, one at a time and re-measuring after each:
- Reseat the dToF connector on **J4**; confirm orientation/lock.
- Temporarily move the module to **J3** and run `case 1` to compare i2c4 vs i2c5 behavior.
- Inspect cable/strain; confirm module power.
- (Optional, eye-safe) verify VCSEL emission with a phone camera in the dark — but note the
  raw histogram is already healthy, so emission is likely fine; this is a last resort.

---

## 8. Acceptance checklist (unchanged from project goal)

- [ ] Car does not move; no actuator/MCU/CAN path started, at any point.
- [ ] Official `case 2` on J4/sensor3: under close occlusion, **most valid distances < 1 m**.
- [ ] Official `case 4`: camera + dToF run together, dToF still correct (watch i2c5).
- [ ] VM stably receives 4873-byte / 40×30 / UDP 2368.
- [ ] Foxglove shows camera, dToF pseudo-color depth, obstacle blocks, health.
- [ ] Every result has a saved log + reproducible command; findings written to `docs/`.

## 9. Evidence index
- Raw-vs-output baseline: `logs/board_auto_ssh_20260531_*.log` (`[DTOF_DBG]` lines).
- Pending-test definition + 06-01 baseline: `docs/dtof_yolo_diagnostic_20260601.md`.
- Source of truth: `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/`
  (`sample_dtof.c`, `dtof_dumpraw.c`, `dtof.ini`, `gs1860_register.ini`, `dtof_init.sh`).
- Case→sensor map: `sample_dtof.c` `sample_dtof_usage()` / `sample_dtof_execute_case()`.

---

## 10. 2026-06-02 continuation status

Read-only checks after the latest continuation confirmed:

- Board SSH at `192.168.137.2` is reachable and the board can ping the VM at
  `192.168.137.100`.
- No `sample_dtof` or RTSP process is currently running on the board.
- `sample_dtof` and `sample_dtof_official_dbg` on the board still match the expected
  SHA256 values.
- `dtof.ini` is still in the official/default critical state:
  `configSwitchFlag=false`, `echoNum=2`, `echoOrderType=1`, `TimeFilter.weight=10.0`,
  and `timeFilterFlag=true`.
- SS928 media modules are loaded (`ot_mipi_rx`, `ot_isp`, `ot_vi`, `ot_base`).
- VM `foxglove_bridge` is listening on `0.0.0.0:8765`; UDP `2368` is idle.
- Phase 1 physical-condition reports are still missing for:
  `clear_official`, `near30cm_official`, and `covered_official`.

The current gate remains Phase 1. Do not deploy Phase 2 `dtof.ini` candidates yet. The
next executable capture is:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition clear_official --binary sample_dtof_official_dbg --seconds 35 --max-packets 120
```

Purpose: capture the J4/case2 official diagnostic baseline in a clear scene.

Risk: starts only the board dToF sample and the VM UDP listener. It has no actuator path
and cannot move the vehicle. It still changes runtime state, so it must be run only after
the user confirms the physical scene is clear and approves starting the perception sample.

Additional source conclusion from this continuation:

- `set_dump_pipe_attr()` still forces the dump pipe from the default `RAW12 + LINE` to
  `RAW10 + NONE` unless `DTOF_KEEP_PIPE_ATTR` is compiled.
- `deal_frame_data()` only unpacks normal raw rows by bit width. It does not decode
  `OT_COMPRESS_MODE_LINE` frames. Therefore keepattr is useful only to prove that bytes
  continue to arrive and can vary with physical conditions; keepattr output is not a valid
  production depth path unless line-compressed Bayer decoding is implemented or the VI path
  is made to emit true uncompressed raw.
- A production-quality fix still needs steady-state official evidence after frame 3:
  non-zero raw and near obstruction producing mostly `<1 m` valid distances.

---

## 11. 2026-06-02 near-object evidence

The user clarified that a close object has been present in front of the dToF lens.
Three near-object captures were run without starting any actuator path:

- `near30cm_official`:
  - Logs:
    `logs/dtof_phase1_near30cm_official_20260602_110425_board.log`,
    `logs/dtof_phase1_near30cm_official_20260602_110425_vm.log`,
    `logs/dtof_phase1_near30cm_official_20260602_110425_report.json`.
  - First two frames are captured before the official dump pipe switches from
    `pixfmt=21 compress=4` to `pixfmt=20 compress=0`.
  - First two frames show the near object is seen by the sensor/algorithm:
    `raw_nonzero=8220`, `raw_max=1023`, `out_max=179 mm`.
  - From frame 3 onward, raw is zero and output is all 2 mm:
    `raw_zero_first_frame=3`, `ALL_2MM_PACKETS=118/120`.

- `near30cm_force500_official`:
  - Logs:
    `logs/dtof_phase1_near30cm_force500_official_20260602_110631_board.log`,
    `logs/dtof_phase1_near30cm_force500_official_20260602_110631_vm.log`,
    `logs/dtof_phase1_near30cm_force500_official_20260602_110631_report.json`.
  - Result is the same as `near30cm_official`: first two frames see `179 mm`, then
    frame 3 onward raw is zero and UDP is dominated by all-2mm packets.
  - Therefore forced 500 ps is not the immediate blocker; it is masked by the same
    post-switch raw-zero failure.

- `near30cm_raw10_start_official`:
  - Logs:
    `logs/dtof_phase1_near30cm_raw10_start_official_20260602_110733_board.log`,
    `logs/dtof_phase1_near30cm_raw10_start_official_20260602_110733_vm.log`,
    `logs/dtof_phase1_near30cm_raw10_start_official_20260602_110733_report.json`.
  - This build starts as `pixfmt=20 compress=0` and therefore avoids a runtime pipe
    attribute transition, but raw is zero from frame 1:
    `raw_zero_first_frame=1`, `ALL_2MM_PACKETS=120/120`.
  - This disproves the simple fix "start the VI pipe as RAW10/NONE".

Comparison report:

```text
logs/dtof_phase1_near30cm_compare_20260602_110733.json
```

Current conclusion:

- The module and optical path can detect the close object: the official run's first
  two frames produce `out_max=179 mm`.
- The live/steady failure is not "dToF cannot see 30 cm"; it is the board-side data
  path after or under `RAW10 + NONE`.
- The next fix should not tune `dtof.ini` first. The immediate target is a valid
  steady raw input path for `DtofProcess`: either make uncompressed raw delivery work
  for GS1860/J4, or implement/choose the correct decoder/path for the existing
  `RAW12 + LINE` frame stream before feeding `DtofProcess`.

## 12. 2026-06-02 MIPI-side analysis addendum

The proposed direction "stop brute-forcing formats; isolate with J3/case1; diff the
GS1860 path against open_camera/sample_vio" is mostly correct, but historical logs refine
the priority:

- Do not continue random RAW10/RAW12/compress-mode combinations. Current evidence already
  localizes the failure to the steady raw-input path after or under the official
  `RAW10 + NONE` dump configuration.
- J3/case1 is still a useful confirmation test if the module is physically moved to J3.
  However, it is no longer a clean "J4-only" discriminator:
  `logs/board_auto_ssh_20260531_014144_7d3fbb00.log` shows `sample_dtof_dbg_frameinfo 1`
  on case1/J3 also transitions to `pixfmt=20 compress=0`, then from frame 3 onward
  `raw_nonzero=0`, `out_max=2`, and `out_eq_2=1200`.
- The paired J3 keepattr log
  `logs/board_auto_ssh_20260531_014236_5c970e08.log` keeps `pixfmt=21 compress=4` and
  continues to show non-zero raw frames (`raw_max=1023`, `raw_nonzero≈14800`). This mirrors
  the J4 behavior: keep the original `RAW12 + LINE` pipe and bytes continue; switch to
  `RAW10 + NONE` and the useful payload disappears.
- Source comparison shows open_camera/sample_vio is not a ready-made alternate decoder:
  its `dtof_dumpraw.c` also changes the dump pipe to `RAW10 + NONE`. Therefore it should
  be used mainly as a reference for MIPI/VI physical mapping and initialization, not as
  proof that `RAW10 + NONE` is valid on this board.
- The notable open_camera differences are in physical mapping, not in dump decoding:
  its GS1860 path manually overrides `mipi_dev`, `combo_dev_attr.devno`, `lane_id[0]`,
  and uses different J3/J4 clock/reset/pipe choices in places. These should be compared
  line by line before any new board-side patch.

Updated root-cause statement:

- The current evidence points to an SDK/sample mismatch around GS1860 raw dumping:
  `vi_bayerdump()` assumes it can force a running GS1860 pipe to `RAW10 + NONE`, but both
  J4 current evidence and J3 historical evidence show that this path can return empty
  payload after the first pre-switch frames.
- The main fix route is to either make the official sample create a genuinely valid
  uncompressed GS1860 raw stream from startup, using the correct MIPI/VI mapping, or to
  keep the original `RAW12 + LINE` stream and implement/locate the proper line-compressed
  raw decoding path before calling `DtofProcess()`.

Additional source findings:

- `src/common/sample_comm_vi.c` in the official MPP tree defines GS1860 as
  `DATA_TYPE_RAW_10BIT`, `WIDTH_2560 x HEIGHT_31`, one MIPI lane:
  - dev2/J3: `g_mipi_1lane_chn0_sensor_gs1860_10bit_1m_nowdr_attr`,
    `devno=2`, `lane_id={4,-1,...}`.
  - dev3/J4: `g_mipi_1lane_chn1_sensor_gs1860_10bit_1m_nowdr_attr`,
    `devno=3`, `lane_id={5,-1,...}`.
- open_camera's `mipi_rgb_dtof` common file only has one GS1860 template with
  `devno=0`, `lane_id={4,-1,...}`; its `imx347.c` call site then manually overrides
  `mipi_dev`, `combo_dev_attr.devno`, and `lane_id[0]` for the selected port. This is a
  mapping/configuration difference worth testing, but it does not by itself explain why
  both J3 and J4 show the same empty-payload behavior after the dump path forces
  `RAW10 + NONE`.
- Local SDK search found no public user-space line-raw decompressor. The available APIs
  are buffer sizing (`ot_buffer.h`), raw frame compression ratio settings
  (`ss_mpi_sys_set/get_raw_frame_compress_param`), and
  `ss_mpi_vi_get_pipe_compress_param()`. Therefore the next diagnostic should first
  confirm whether `RAW12 + LINE` has valid per-pipe compression parameters and stable
  payload bytes under a near object; then decide whether to avoid compression at VI
  startup or investigate a private/internal decode path.

Next state-changing diagnostic candidate:

- Deploy the already-built keepattr + compress-param diagnostic binary
  (`/home/ebaina/official_dtof_rtsp_sensor3_pipe_20260602_112401/src/dtof/sample_dtof_rtsp_sensor3_pipe_dbg`)
  to the board under a non-overwriting name such as
  `/opt/sample/official_dtof/sample_dtof_keepattr_compressparam_dbg`.
- Run it on current J4/case2 with the close object still present and collect board +
  VM logs.
- Expected useful evidence:
  - Whether `ss_mpi_vi_get_pipe_compress_param()` succeeds while the frame remains
    `pixfmt=21 compress=4`.
  - Whether the line-compressed payload rows are stable/non-zero in steady state.
  - Whether `DtofProcess()` output under the unchanged compressed input remains far/invalid,
    confirming that the input bytes require a different decode path before processing.

## 13. 2026-06-02 keepattr + compress-param diagnostic result

The keepattr + compress-param diagnostic was deployed and run on the current J4/case2
near-object setup:

- VM source binary:
  `/home/ebaina/official_dtof_rtsp_sensor3_pipe_20260602_112401/src/dtof/sample_dtof_rtsp_sensor3_pipe_dbg`
- Board binary:
  `/opt/sample/official_dtof/sample_dtof_keepattr_compressparam_dbg`
- SHA256 on VM and board:
  `47b9bf5c4378f2fb5b4236f410ad527f1a95db2a69c98178b54c4e3fad60cc68`
- Logs:
  - `logs/dtof_phase1_near30cm_keepattr_compressparam_20260602_114749_board.log`
  - `logs/dtof_phase1_near30cm_keepattr_compressparam_20260602_114749_vm.log`
  - `logs/dtof_phase1_near30cm_keepattr_compressparam_20260602_114749_report.json`

Evidence:

- The pipe stayed in the original compressed mode for all printed frames:
  `pixfmt=21`, `compress=4`, `stride0=3552`, `w=2560`, `h=31`.
- `ss_mpi_vi_get_pipe_compress_param()` succeeded consistently:
  `ret=0x0`, `cp_sum=5974`, first bytes
  `01 00 00 00 f2 00 00 00 01 00 00 00 01 00 00 00 ...`.
  The same values were printed at frames 1-8 and every 30 frames through frame 630.
- The line-compressed payload is stable and non-zero in steady state:
  `row1_first16=16 00 00 fd 3f a0 ff 0f 82 20 08 82 10 22 92 fa`.
- The current `deal_frame_data()` path is not a valid decoder for this input:
  printed raw stats are `raw_max=4095` and `raw_nonzero≈12400`, while `DtofProcess()`
  output is dominated by the 2 mm sentinel (`out_eq_2=1199` or `1200` for the first
  12 frames).
- VM received 120 valid 4873-byte packets, but the depth content is still unusable:
  `ALL_2MM_PACKETS=15`, most packet means are near 2-14 mm, and the occasional large
  max values are sparse outliers rather than a real near-object depth map.

Conclusion:

- The `RAW12 + LINE` stream itself is present and carries stable compressed payload.
- The immediate software gap is no longer "does the pipe deliver bytes"; it is "how to
  obtain ordinary GS1860 histogram/raw data from a line-compressed VI frame before calling
  `DtofProcess()`."
- Any candidate fix must either:
  1. make VI produce a genuine uncompressed GS1860 raw frame from startup without triggering
     the RAW10/NONE empty-payload failure, or
  2. locate/implement the correct line-compressed raw decode path using the successful
     per-pipe compression parameters before feeding `DtofProcess()`.

## 14. 2026-06-02 source pass after keepattr + compress-param

Read-only source and artifact checks after the keepattr/compress-param run refined the
next gate:

- No public user-space line-compressed raw decoder was found in the local SDK or
  `dtof_sensor_driver-master`. The exposed local APIs are buffer sizing
  (`ot_buffer.h`), raw-frame compression-ratio configuration
  (`ss_mpi_sys_set/get_raw_frame_compress_param`), and
  `ss_mpi_vi_get_pipe_compress_param()`.
- `dtof_dumpraw.c::set_dump_pipe_attr()` changes only `pixel_format` and
  `compress_mode` when forcing the dump pipe to `RAW10 + NONE`. The previously built
  `DTOF_FORCE_RAW10_NONE` startup variant did allocate the raw VB pool as
  `RAW10 + NONE`, but its near-object run still produced raw zero from frame 1. This
  makes a simple VB-size mismatch unlikely as the sole cause.
- `sample_dtof.c` still leaves `pipe_attr.bit_width` at the common default
  `OT_DATA_BIT_WIDTH_8`, including in the raw10 startup macro path. This remains a
  bounded variable, but it is not enough to explain the already observed
  `RAW10 + NONE` startup failure without a controlled run that changes only this.
- open_camera's `mipi_rgb_dtof` GS1860 path is useful as a mapping reference, not as a
  ready decoder. Its J4 path differs from the official sample mainly by using
  `sns_clk_src=0`, `sns_rst_src=0`, explicitly setting `mipi_dev=3`, `devno=3`,
  `lane_id[0]=5`, `ext_data_type_attr.devno=3`, and setting
  `chn_need_start=TD_FALSE`.
- The board already contains three related diagnostic binaries, but their evidence
  chain is incomplete because paired board/VM near-object UDP reports were not found:
  - `/opt/sample/official_dtof/sample_dtof_official_j4cfg_dbg`
    (`a6398c9c...a7b56c`)
  - `/opt/sample/official_dtof/sample_dtof_official_bitwidth_dbg`
    (`b03a321c...866f18f`)
  - `/opt/sample/official_dtof/sample_dtof_official_feout_dbg`
    (`7d22f7d...fe4905`)
- The next state-changing test should therefore be a single controlled candidate run,
  not another broad format sweep. The best first candidate is
  `sample_dtof_official_j4cfg_dbg` because it tests the open_camera-style J4 mapping
  while keeping the official depth-processing path.

Proposed next command, if the user approves starting a perception-only dToF sample:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_j4cfg_official --binary sample_dtof_official_j4cfg_dbg --seconds 35 --max-packets 120
```

Purpose: test whether the open_camera-style J4 GS1860 mapping changes the steady-state
`RAW10 + NONE` raw-zero behavior under the current near-object setup.

Risk: starts only the board dToF sample and VM UDP listener. It has no actuator path and
cannot move the vehicle, but it changes board/VM runtime perception state, so it must be
run only after explicit user approval.

Pass/fail gate:

- Pass: steady-state frames after frame 3 keep non-zero raw and VM UDP depth reports a
  near object with most valid distances `<1 m`.
- Fail: raw still becomes zero after the pipe switch, or UDP remains all/mostly 2 mm or
  sparse far outliers. In that case, do not keep tuning `dtof.ini`; move to a bit-width
  isolated run or the line-compressed raw decode path.

## 15. 2026-06-02 preflight before `near30cm_j4cfg_official`

Read-only preflight checks show the next controlled run can be made without first
cleaning up stale processes:

- Board `/opt/sample/official_dtof` has no old `sample_dtof` or RTSP process running.
- VM has `foxglove_bridge` running, but no UDP `2368` listener occupying the dToF
  capture port.
- Board candidate binaries are present and match the VM build hashes:
  - `sample_dtof_official_j4cfg_dbg`:
    `a6398c9cb6c36c3bf36b97ea8c0d8bc00fbfd3c3c8467a307d18f06353a7b56c`
  - `sample_dtof_official_bitwidth_dbg`:
    `b03a321ce81f052db36b27582dd7f3a5553c08b483aea12c50104b3a4866f18f`
  - `sample_dtof_official_feout_dbg`:
    `7d22f7d84c8fdda64caa43910fcbcf822a75515354953876b871b5cdbdfe4905`

The next state-changing command remains:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_j4cfg_official --binary sample_dtof_official_j4cfg_dbg --seconds 35 --max-packets 120
```

Do not run it until the user explicitly approves starting this perception-only board
sample and VM UDP capture.

## 16. 2026-06-02 `near30cm_j4cfg_official` result

The approved/default-approved perception-only j4cfg candidate run was executed:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_j4cfg_official --binary sample_dtof_official_j4cfg_dbg --seconds 35 --max-packets 120
```

Logs:

- `logs/dtof_phase1_near30cm_j4cfg_official_20260602_121001_commands.txt`
- `logs/dtof_phase1_near30cm_j4cfg_official_20260602_121001_board.log`
- `logs/dtof_phase1_near30cm_j4cfg_official_20260602_121001_vm.log`
- `logs/dtof_phase1_near30cm_j4cfg_official_20260602_121001_report.json`

Result:

- The board sample did not reach any `[DTOF_OFFICIAL_DBG] frame=...` capture lines.
- The j4cfg binary printed:
  `sensor3_j4_cfg bus=5 clk=0 rst=0 mipi_dev=3 lane0=5 chn_start=0`.
- It then failed during VI/ISP startup:
  `OT_MPI_ISP_MemInit failed with 0xa010800b`,
  `[sample_comm_vi_start_vi]-1886: start isp failed!`,
  `program exit abnormally!`,
  `DTOF_PHASE1_RC=255`.
- VM UDP capture received no packets:
  `PACKETS=0`, `GOOD_SIZE_4873=0`, `DTOF_UDP_CHECK=FAIL`.
- A post-run read-only board check showed no stale `sample_dtof`/RTSP process remained
  and the media modules were still loaded.

Local report tooling was updated so this failure class is no longer hidden as
`undetermined`; it now classifies as:

```text
gate = startup_failed
```

Conclusion:

- `sample_dtof_official_j4cfg_dbg` is not a valid near-depth fix candidate as built.
  Its open_camera-style J4 mapping variant fails before frame acquisition, so it gives no
  evidence about the steady-state RAW10/NONE raw-zero bug.
- The failure is specifically tied to the candidate configuration that changes sensor3/J4
  to `clk=0`, `rst=0`, `mipi_dev=3`, `lane0=5`, and `chn_need_start=TD_FALSE`.
- Do not rerun this j4cfg binary as-is. The next controlled software gate should be either
  the already-deployed bit-width isolated candidate
  `sample_dtof_official_bitwidth_dbg`, or a focused line-compressed RAW decode path.

Current suite status:

- `near30cm_official`: `pipe_attr_zero_after_switch`; first two frames see the close
  target (`out_max=179 mm`), then raw becomes zero at frame 3 and UDP is dominated by
  all-2mm packets.
- `near30cm_j4cfg_official`: `startup_failed`; no frames and no UDP packets.
- `clear_official` and `covered_official` remain missing as physical-condition reports.

Safety note: no actuator, MCU bridge, CAN, serial actuator, motor, steering, brake, or
throttle process was started. The run touched only the board dToF sample and VM UDP
listener.

## 17. 2026-06-02 `near30cm_bitwidth_official` result

After the j4cfg startup failure, the already-deployed bit-width isolated candidate was
checked and run under the same near-object setup:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_bitwidth_official --binary sample_dtof_official_bitwidth_dbg --seconds 35 --max-packets 120
```

Candidate scope:

- Source check showed this candidate changes `set_dump_pipe_attr()` to set
  `pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10` while leaving the official RAW10/NONE dump
  path otherwise intact.
- Board SHA:
  `b03a321ce81f052db36b27582dd7f3a5553c08b483aea12c50104b3a4866f18f`.

Logs:

- `logs/dtof_phase1_near30cm_bitwidth_official_20260602_121346_commands.txt`
- `logs/dtof_phase1_near30cm_bitwidth_official_20260602_121346_board.log`
- `logs/dtof_phase1_near30cm_bitwidth_official_20260602_121346_vm.log`
- `logs/dtof_phase1_near30cm_bitwidth_official_20260602_121346_report.json`

Result:

- The board binary crashed before any debug frame was emitted:
  `Segmentation fault`, `DTOF_PHASE1_RC=139`.
- VM UDP capture received no packets:
  `PACKETS=0`, `GOOD_SIZE_4873=0`, `DTOF_UDP_CHECK=FAIL`.
- Post-run read-only checks again showed no stale `sample_dtof`/RTSP process and no VM
  UDP 2368 listener left behind.
- Report gate:

```text
gate = startup_failed
```

Conclusion:

- The isolated `bit_width=10` change is not a viable fix as built; it crashes before
  frame acquisition.
- Current near-object evidence now rules out two narrow candidate fixes:
  j4/open_camera-style mapping as built (`startup_failed`) and bit-width-only RAW10/NONE
  adjustment (`startup_failed`).
- The primary route remains the steady raw-input problem: either find a valid
  uncompressed GS1860 VI startup path without the RAW10/NONE empty-payload behavior, or
  implement/locate a correct decode path for the existing `RAW12 + LINE` compressed frame
  stream before `DtofProcess()`.
- Do not tune ROS/Foxglove thresholds or `dtof.ini` to mask this. The dToF acceptance
  gate is still official J4/case2 steady-state near-object output with most valid
  distances `<1 m`.

Safety note: no actuator, MCU bridge, CAN, serial actuator, motor, steering, brake, or
throttle process was started. The run touched only the board dToF sample and VM UDP
listener.

## 18. 2026-06-02 media-stack dirty state after failed candidates

After the bit-width and RAW12-startup candidate attempts, a short clean-official run was
made to check whether the board media stack was still healthy:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_official_post_raw12_state --binary sample_dtof_official_dbg --seconds 15 --max-packets 40
```

Logs:

- `logs/dtof_phase1_near30cm_official_post_raw12_state_20260602_122303_commands.txt`
- `logs/dtof_phase1_near30cm_official_post_raw12_state_20260602_122303_board.log`
- `logs/dtof_phase1_near30cm_official_post_raw12_state_20260602_122303_vm.log`
- `logs/dtof_phase1_near30cm_official_post_raw12_state_20260602_122303_report.json`

Result:

- The clean official debug binary failed before any frame was acquired:
  `ISP[1] already inited`, `OT_MPI_ISP_MemInit failed with 0xa01c800c`,
  `start isp failed`, `DTOF_PHASE1_RC=255`.
- VM UDP capture received no packets:
  `PACKETS=0`, `DTOF_UDP_CHECK=FAIL`.
- Report gate:

```text
gate = startup_failed
```

Conclusion:

- The prior failed startup/crash candidates left the SS928 media stack in a dirty ISP/VI
  state. A clean-official control run could not start until the media stack was reloaded.
- This is a board media-stack cleanup issue, not a dToF depth-quality result.

The following state-changing board command was shown with purpose and risk, then run
under the user's default board/VM approval:

```powershell
$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python tools\board_run.py "cd /opt/ko && ./load_ss928v100 -a -sensor0 os08a20 -sensor1 os08a20 -sensor2 os08a20 -sensor3 os08a20"
```

Purpose: reload the SS928 media stack after ISP/VI dirty-state failures.

Risk: reloads board media modules and interrupts perception pipelines, but it does not
touch MCU bridge, CAN, serial actuator, motor, steering, brake, throttle, or any chassis
control path.

Reload output included:

```text
os_mem_size: 1024
mem_total: 4096
mmz_start: 0x90000000, mmz_size: 2816M
```

Post-reload read-only checks showed no stale `sample_dtof`/RTSP process, media modules
loaded, and VM UDP 2368 idle.

## 19. 2026-06-02 clean official control after media reload

After reloading the media stack, the clean official debug binary was run again:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_official_after_media_reload --binary sample_dtof_official_dbg --seconds 15 --max-packets 40
```

Logs:

- `logs/dtof_phase1_near30cm_official_after_media_reload_20260602_122433_commands.txt`
- `logs/dtof_phase1_near30cm_official_after_media_reload_20260602_122433_board.log`
- `logs/dtof_phase1_near30cm_official_after_media_reload_20260602_122433_vm.log`
- `logs/dtof_phase1_near30cm_official_after_media_reload_20260602_122433_report.json`

Result:

- The media stack was restored enough for the official sample to run.
- Frames 1-2 again showed that the close object is visible before the pipe-attribute
  switch:
  `pixfmt=21`, `compress=4`, `raw_nonzero=8220`, `raw_max=1023`,
  `out_max=179 mm`.
- From frame 3 onward, the official dump path switched to
  `pixfmt=20`, `compress=0`; raw became zero and depth became all 2 mm:
  `raw_zero_first_frame=3`, `all_2mm_first_frame=3`.
- VM received valid official-sized dToF packets:
  `PACKETS=40`, `GOOD_SIZE_4873=40`, `GOOD_HEADER_40x30=40`,
  `VALIDISH_DEPTH_PACKETS=2`, `ALL_2MM_PACKETS=38`, `DTOF_UDP_CHECK=PASS`.
- Report gate:

```text
gate = pipe_attr_zero_after_switch
```

Conclusion:

- Media reload recovered the board from the ISP dirty state.
- The core official-path failure remains unchanged: `RAW12 + LINE` frames before the
  switch contain useful near-object evidence, but the official `RAW10 + NONE` dump path
  returns zero raw from frame 3 onward.
- This reconfirms that the next work must focus on a valid steady raw input path before
  ROS/Foxglove thresholds are trusted.

## 20. 2026-06-02 RAW12/NONE startup candidate with force-500ps caveat

A RAW12/NONE-from-startup candidate was built from the official MPP dToF baseline using
`tools/vm_build_official_raw12_start.sh`:

- VM build log: `logs/vm_ssh_20260602_122029_37a69e5e.log`
- VM build directory:
  `/home/ebaina/official_dtof_raw12_start_debug_20260602_122025`
- VM and board binary:
  `sample_dtof_official_raw12_start_dbg`
- SHA256:
  `198a157cbd084dba4cffa8befb33447926ef9a12c8a933ce60220e235bcc1739`
- Board deploy log: `logs/vm_ssh_20260602_122057_d66db365.log`

The first run, before media reload, failed with the same dirty-state startup symptom:

- Logs:
  `logs/dtof_phase1_near30cm_raw12_start_official_20260602_122124_board.log`,
  `logs/dtof_phase1_near30cm_raw12_start_official_20260602_122124_vm.log`,
  `logs/dtof_phase1_near30cm_raw12_start_official_20260602_122124_report.json`.
- Result:
  `ISP[1] already inited`, `OT_MPI_ISP_MemInit failed with 0xa01c800c`,
  `DTOF_PHASE1_RC=255`, `PACKETS=0`.
- Report gate:

```text
gate = startup_failed
```

After the media reload, the same binary was run:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_raw12_start_after_reload --binary sample_dtof_official_raw12_start_dbg --seconds 15 --max-packets 40
```

Logs:

- `logs/dtof_phase1_near30cm_raw12_start_after_reload_20260602_122504_commands.txt`
- `logs/dtof_phase1_near30cm_raw12_start_after_reload_20260602_122504_board.log`
- `logs/dtof_phase1_near30cm_raw12_start_after_reload_20260602_122504_vm.log`
- `logs/dtof_phase1_near30cm_raw12_start_after_reload_20260602_122504_report.json`

Result:

- The sample ran and stayed at `pixfmt=21`, `compress=0`, but raw was zero from the
  first debug frame:
  `raw_zero_first_frame=1`, `raw_nonzero=0`, `raw_max=0`.
- VM received 40 official-sized UDP packets, all 2 mm:
  `PACKETS=40`, `GOOD_SIZE_4873=40`, `ALL_2MM_PACKETS=40`,
  `DTOF_UDP_CHECK=PASS`.
- Report gate:

```text
gate = raw_zero_from_start
```

Caveat:

- This binary used `artifacts/official_dtof_dumpraw_debug.c`, which hard-defines the
  forced-500ps diagnostic path. The board log contains:
  `[DTOF_OFFICIAL_DBG] force gs1860 500ps config`.
- Because of that contamination, this run is not the clean final RAW12/NONE startup
  discriminator. A no-500ps rebuild was made and run next.

## 21. 2026-06-02 clean RAW12/NONE startup no-500ps result

To remove the force-500ps contamination, the RAW12 startup build was repeated with
`artifacts/official_dtof_dumpraw_feout_debug.c` as the dumpraw source and
`RAW12_EXTRA_CFLAGS` set to keep pipe-source dumping:

- Build script:
  `tools/vm_build_official_raw12_start.sh`
- Build command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 240 --allow-risk run "chmod +x /tmp/vm_build_official_raw12_start.sh && BUILD=/home/ebaina/official_dtof_raw12_start_no500_debug_20260602_1226 BINARY_NAME=sample_dtof_official_raw12_start_no500_dbg /tmp/vm_build_official_raw12_start.sh"
```

- VM build log: `logs/vm_ssh_20260602_122733_1e63a59a.log`
- VM build directory:
  `/home/ebaina/official_dtof_raw12_start_no500_debug_20260602_1226`
- Board binary:
  `/opt/sample/official_dtof/sample_dtof_official_raw12_start_no500_dbg`
- SHA256:
  `2f81c8034f3179ccdb570a25119440fa3a39985700aae6d8aa61173345d0697b`
- Board deploy log: `logs/vm_ssh_20260602_122751_afb62da9.log`

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_raw12_start_no500_official --binary sample_dtof_official_raw12_start_no500_dbg --seconds 15 --max-packets 40
```

Logs:

- `logs/dtof_phase1_near30cm_raw12_start_no500_official_20260602_122811_commands.txt`
- `logs/dtof_phase1_near30cm_raw12_start_no500_official_20260602_122811_board.log`
- `logs/dtof_phase1_near30cm_raw12_start_no500_official_20260602_122811_vm.log`
- `logs/dtof_phase1_near30cm_raw12_start_no500_official_20260602_122811_report.json`

Result:

- No forced-500ps line appeared in the board log.
- The frame stream was `RAW12 + NONE` from startup:
  `w=2560`, `h=31`, `stride0=3840`, `pixfmt=21`, `compress=0`.
- The payload rows that should contain dToF histogram data were zero from frame 1:
  `row_sum32=1052/0/0` on frame 1, increasing only in the first row; `row1_first16`
  stayed all zero.
- `DtofProcess()` input/output stayed invalid:
  `raw_nonzero=0`, `raw_max=0`, `out_max=2`, `out_eq_2=1200` for every printed frame.
- VM received valid official-sized UDP packets but all were the 2 mm sentinel:
  `PACKETS=40`, `GOOD_SIZE_4873=40`, `GOOD_HEADER_40x30=40`,
  `VALIDISH_DEPTH_PACKETS=0`, `ALL_2MM_PACKETS=40`, `DTOF_UDP_CHECK=PASS`.
- Report gate:

```text
gate = raw_zero_from_start
```

Conclusion:

- Clean `RAW12 + NONE` from startup is also a valid negative result: it produces zero
  dToF raw payload from the first frame under the near-object setup.
- Current controlled tests have now ruled out:
  - the j4/open_camera-style mapping candidate as built (`startup_failed`);
  - bit-width-only RAW10/NONE adjustment (`startup_failed`);
  - RAW10/NONE startup (`raw_zero_from_start`, from section 11);
  - clean RAW12/NONE startup (`raw_zero_from_start`).
- The only currently proven path carrying steady dToF payload is the original
  `RAW12 + LINE` compressed stream. Its bytes and pipe compression parameters are
  present, but the current `deal_frame_data()` path does not decode that stream before
  `DtofProcess()`.
- The next technical route should be focused and non-random:
  1. locate a vendor/private path to obtain decompressed GS1860 raw from the VI/MIPI
     stream, or
  2. implement/validate line-compressed RAW12 decoding using
     `ss_mpi_vi_get_pipe_compress_param()` and the observed stable compressed rows.

Do not tune ROS thresholds or treat the 2 mm sentinel as a real near obstacle. The
acceptance gate remains steady-state official J4/case2 near-object output with most
valid distances `<1 m`.

Safety note: no actuator, MCU bridge, CAN, serial actuator, motor, steering, brake, or
throttle process was started during these diagnostics. The only board/VM state changes
were perception-sample runs, binary deployment to `/opt/sample/official_dtof`, and the
SS928 media-stack reload described above.

## 22. 2026-06-02 RAW12+LINE frame-dump evidence

To stop reasoning from only `row1_first16` excerpts, a new official-baseline diagnostic
was built. It keeps the original GS1860 pipe attributes (`RAW12 + LINE`), records the
per-pipe compression parameters, and saves the first four compressed frame buffers for
offline analysis.

Build scripts and binaries:

- Script:
  `tools/vm_build_official_line_dump.sh`
- Source template:
  `artifacts/dtof_dumpraw_keepattr_compressparam.c`
- First line-dump binary:
  - VM build log: `logs/vm_ssh_20260602_123955_d3b8372c.log`
  - VM binary:
    `/home/ebaina/official_dtof_line_dump_debug_20260602_123950/src/dtof/sample_dtof_official_line_dump_dbg`
  - Board binary:
    `/opt/sample/official_dtof/sample_dtof_official_line_dump_dbg`
  - SHA256:
    `e99d2938179dd5a9de5d025fbeb8792f60e39b4c2846c1f93578eeb675432832`
- Full-compress-param line-dump binary:
  - VM build log: `logs/vm_ssh_20260602_124410_1bb012f0.log`
  - VM binary:
    `/home/ebaina/official_dtof_line_dump_debug_20260602_124406/src/dtof/sample_dtof_official_line_dump_cp_dbg`
  - Board binary:
    `/opt/sample/official_dtof/sample_dtof_official_line_dump_cp_dbg`
  - SHA256:
    `3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea`

Run commands:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_line_dump_official --binary sample_dtof_official_line_dump_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_line_dump_cp_official --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Logs:

- `logs/dtof_phase1_near30cm_line_dump_official_20260602_124100_board.log`
- `logs/dtof_phase1_near30cm_line_dump_official_20260602_124100_vm.log`
- `logs/dtof_phase1_near30cm_line_dump_official_20260602_124100_report.json`
- `logs/dtof_phase1_near30cm_line_dump_cp_official_20260602_124450_board.log`
- `logs/dtof_phase1_near30cm_line_dump_cp_official_20260602_124450_vm.log`
- `logs/dtof_phase1_near30cm_line_dump_cp_official_20260602_124450_report.json`

Downloaded frame artifacts:

- `artifacts/dtof_line_dump_20260602_124100/`
- `artifacts/dtof_line_dump_cp_20260602_124450/`
- Offline structure report:
  `artifacts/dtof_line_dump_cp_20260602_124450/line_dump_analysis.json`

Board/UDP result:

- The pipe stayed at the original compressed format for all debug frames:
  `pixfmt=21`, `compress=4`, `w=2560`, `h=31`, `stride0=3552`.
- `ss_mpi_vi_get_pipe_compress_param()` returned success with stable parameters:
  `ret=0x0`, `cp_sum=5974`.
- The full `compress_param` size is 152 bytes
  (`OT_VI_COMPRESS_PARAM_SIZE=152`), not just the first 32 bytes printed in earlier
  logs.
- The first 16 little-endian u32 values in the 152-byte parameter block are:

```text
[1, 242, 1, 1, 0, 0, 2, 2560, 31, 1, 8, 1, 45, 6, 4, 30]
```

- VM UDP still had official packet transport:
  `PACKETS=20`, `GOOD_SIZE_4873=20`, `GOOD_HEADER_40x30=20`,
  `DTOF_UDP_CHECK=PASS`.
- But the output was not a real near-depth image. It was sparse invalid/far output:
  `out_eq_2` was `1199` or `1200` out of 1200 pixels, and the UDP summaries had
  only 1-3 unique depth values per packet.
- After updating `tools/dtof_phase1_log_report.py`, the full-compress-param run is
  classified as:

```text
gate = line_compressed_stream_not_decoded
```

Offline frame-buffer structure:

- Each saved frame is 110112 bytes (`31 * 3552`).
- `compress_param` is identical across the four saved frames.
- Most measurement rows are byte-identical within and across frames.
- The common measurement row has only 342 nonzero bytes; the rest of the 3552-byte
  stride is zero.
- The first 64 bytes of the common row are mask-like/compressed bytes beginning with:

```text
16 00 00 fd 3f a0 ff 0f 82 20 08 82 10 22 92 fa
ff f7 ff ff ff ef ff ff ff df ff ff ff bf ff ff
```

- Differences between frames are mostly in row 0 and occasional 12-byte patches in a
  single measurement row. This is not shaped like an already-expanded
  `40 * 30 * 64` GS1860 histogram.

Conclusion:

- The `RAW12 + LINE` stream is real and stable, but it is a compressed/opaque row stream.
- The current `deal_frame_data()` ordinary RAW12 unpack path is reading that compressed
  stream incorrectly. Its sparse 2mm/far UDP result should not be interpreted as depth.
- The main remaining software gap is precise decoding or bypassing of
  `OT_COMPRESS_MODE_LINE` for GS1860 before `DtofProcess()`.
- Local SDK headers expose `ss_mpi_vi_get_pipe_compress_param()` and the opaque
  152-byte `ot_vi_compress_param`, but no public user-space decompressor was found in
  the local SDK/open_camera sources. A brief public web search for
  `ot_vi_compress_param`, `ss_mpi_vi_get_pipe_compress_param`, and
  `OT_COMPRESS_MODE_LINE raw line compression` also did not locate a usable format
  specification.

Next route:

1. Ask Ebaina/HiSilicon documentation or support for the SS928 raw line-compression
   format or the official way to obtain decompressed GS1860 raw frames.
2. If documentation is unavailable, build a controlled reverse-engineering harness using
   the saved frame dumps plus additional physical conditions. The harness must validate
   any decoder by producing a full `30 * 40 * 64` raw histogram that makes
   `DtofProcess()` output mostly `<1 m` under the current near obstruction.
3. Do not continue random RAW10/RAW12/NONE/LINE toggles unless a new hypothesis explains
   exactly what variable is being tested.

Safety note: these line-dump diagnostics were perception-only. No actuator, MCU bridge,
CAN, serial actuator, motor, steering, brake, or throttle process was started.

## 23. 2026-06-02 FE_OUT/BAS dump-source control

The `RAW12 + LINE` evidence above left one bounded question: whether another official
dump source could return a decompressed frame while the default pipe source returns the
compressed line buffer. A controlled FE_OUT/BAS comparison was built from the same
official baseline and the same line-dump source template.

Tooling changes:

- `tools/vm_build_official_line_dump.sh` now accepts `DUMP_SOURCE`, defaulting to `0`
  so the previous PIPE behavior is unchanged.
- `tools/analyze_dtof_line_dump.py` was added to make local dump analysis
  reproducible.
- `tools/dtof_phase1_compare_reports.py` now prioritizes
  `line_compressed_stream_not_decoded` when producing the suite route.

Builds:

- FE_OUT:
  - VM binary:
    `/home/ebaina/official_dtof_line_dump_feout_cp_20260602/src/dtof/sample_dtof_official_line_dump_feout_cp_dbg`
  - Board binary:
    `/opt/sample/official_dtof/sample_dtof_official_line_dump_feout_cp_dbg`
  - SHA256:
    `506f70c62482c388afa8c05b89317b24c7a5e21ff848cb659d8d604a77fe770c`
- BAS:
  - VM binary:
    `/home/ebaina/official_dtof_line_dump_bas_cp_20260602/src/dtof/sample_dtof_official_line_dump_bas_cp_dbg`
  - Board binary:
    `/opt/sample/official_dtof/sample_dtof_official_line_dump_bas_cp_dbg`
  - SHA256:
    `70b3cd59aaf48f0933ab5e005e713ad0f2fc3b2331a7a7a21963ac78400296d0`

Run commands:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_line_dump_feout_cp_official --binary sample_dtof_official_line_dump_feout_cp_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_line_dump_bas_cp_official --binary sample_dtof_official_line_dump_bas_cp_dbg --seconds 8 --max-packets 20
```

Logs and artifacts:

- `logs/dtof_phase1_near30cm_line_dump_feout_cp_official_20260602_125819_board.log`
- `logs/dtof_phase1_near30cm_line_dump_feout_cp_official_20260602_125819_vm.log`
- `logs/dtof_phase1_near30cm_line_dump_feout_cp_official_20260602_125819_report.json`
- `artifacts/dtof_line_dump_feout_cp_20260602_125819/`
- `artifacts/dtof_line_dump_feout_cp_20260602_125819/line_dump_analysis.json`
- `logs/dtof_phase1_near30cm_line_dump_bas_cp_official_20260602_130014_board.log`
- `logs/dtof_phase1_near30cm_line_dump_bas_cp_official_20260602_130014_vm.log`
- `logs/dtof_phase1_near30cm_line_dump_bas_cp_official_20260602_130014_report.json`
- `logs/dtof_phase1_suite_status_latest.json`
- `logs/dtof_phase1_suite_compare_latest.json`

FE_OUT result:

- FE_OUT reported `dump_source=fe_out keep vi_pipe 1 attr pixfmt=21 compress=4`.
- Board and UDP metrics matched the PIPE line-dump run:
  `PACKETS=20`, `GOOD_SIZE_4873=20`, `GOOD_HEADER_40x30=20`,
  `out_eq_2` median `1199`, and report gate
  `line_compressed_stream_not_decoded`.
- The first four FE_OUT dump files are byte-identical to the earlier PIPE dump files:
  - frame 1 SHA256:
    `fa5ede25d845d9df97a4e23e5e9c4e1618a3c6cda3230a49c32e9d9e5d838fcf`
  - frame 2 SHA256:
    `1c937c13e16986b172569cd36a61395b71e495d165c0d14fc538703d8f752db7`
  - frame 3 SHA256:
    `f2744b52f387d723d2077275708ddf324f6451073fb6b57b2e8197e1ec4207cd`
  - frame 4 SHA256:
    `baac972ff1df85bbb093320138d9d58c2044aae96b4741069e01282d21572602`
- The 152-byte compress parameter also matched PIPE:
  `647057ba5f7082a05286f32fd737c0c005586a032bbe3f84e8427213b95e0c9a`.

BAS result:

- BAS reported `dump_source=bas keep vi_pipe 1 attr pixfmt=21 compress=4`, then failed
  to obtain frames:

```text
Linear:get vi_pipe 1 frame err!
Linear:get vi_pipe 1 frame err!
```

- No debug frames were produced, VM received no UDP packets, and the report gate is
  `startup_failed`.

Conclusion:

- PIPE and FE_OUT are not two useful independent frame representations in this setup;
  they return the same `RAW12 + LINE` compressed buffer.
- BAS is not usable for this dToF pipe as currently configured.
- This closes the bounded dump-source hypothesis. The current route remains:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

- The next useful work is to obtain the SS928/HiSilicon RAW line-compression decode
  specification or an official API/path that yields decompressed GS1860 raw frames.
  Without that, any user-space decoder must be validated against saved dumps plus new
  physical-condition dumps and must make `DtofProcess()` produce mostly `<1 m` for the
  near obstruction before ROS/Foxglove is trusted.

Safety note: these FE_OUT/BAS diagnostics were perception-only. No actuator, MCU bridge,
CAN, serial actuator, motor, steering, brake, or throttle process was started.

## 24. 2026-06-02 RAW16/NONE after-start dump control

After FE_OUT returned the same compressed buffer as PIPE and BAS failed to obtain frames,
one remaining bounded software hypothesis was tested: the SDK `dynamic_blc_online_cali`
sample changes a running VI pipe to `RAW16 + NONE` for calibration dumping and allocates
a RAW16/NONE raw VB pool. A dToF-specific version of that method was built to see whether
it can obtain decompressed GS1860 histogram data after the official `RAW12 + LINE`
startup path.

Build:

- Script:
  `tools/vm_build_official_raw16_afterstart.sh`
- VM binary:
  `/home/ebaina/official_dtof_raw16_afterstart_debug_20260602/src/dtof/sample_dtof_official_raw16_afterstart_dbg`
- Board binary:
  `/opt/sample/official_dtof/sample_dtof_official_raw16_afterstart_dbg`
- SHA256:
  `fed509d7f062eb673cc0642ffe3e97d0dc1de05716340951a8d3bbc7eae57e80`

Patch intent:

- Keep the official dToF startup path.
- Allocate the raw VB pool as `OT_PIXEL_FORMAT_RGB_BAYER_16BPP` plus
  `OT_COMPRESS_MODE_NONE`.
- In `set_dump_pipe_attr()`, change the dump pipe to `RAW16 + NONE`
  (`pixfmt=23`, `compress=0`) instead of the official RAW10/NONE switch.
- Keep all diagnostics perception-only and under `/opt/sample/official_dtof`.

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_raw16_afterstart_official --binary sample_dtof_official_raw16_afterstart_dbg --seconds 12 --max-packets 40
```

Logs:

- `logs/dtof_phase1_near30cm_raw16_afterstart_official_20260602_131042_commands.txt`
- `logs/dtof_phase1_near30cm_raw16_afterstart_official_20260602_131042_board.log`
- `logs/dtof_phase1_near30cm_raw16_afterstart_official_20260602_131042_vm.log`
- `logs/dtof_phase1_near30cm_raw16_afterstart_official_20260602_131042_report.json`
- Updated suite:
  `logs/dtof_phase1_suite_status_latest.json`
- Updated comparison:
  `logs/dtof_phase1_suite_compare_latest.json`

Result:

- The diagnostic did request the intended pipe switch:

```text
[DTOF_DBG] dump_source=pipe set vi_pipe 1 attr pixfmt=23 compress=0 rawdepth=2
```

- Frames 1-2 were still the previous `RAW12 + LINE` compressed buffers:
  `pixfmt=21`, `compress=4`, `stride0=3552`.
- From frame 3 onward, the pipe did switch to the requested RAW16/NONE shape:
  `pixfmt=23`, `compress=0`, `stride0=5120`.
- The switched RAW16/NONE measurement rows were zero:
  `row_sum32=1090/0/0` on frame 3, `row1_first16` all zero, and
  `raw_nonzero=0`, `raw_max=0` for frames 3-12.
- UDP transport still passed packet-format checks:
  `PACKETS=40`, `GOOD_SIZE_4873=40`, `GOOD_HEADER_40x30=40`.
- Depth output was not valid near-depth:
  `VALIDISH_DEPTH_PACKETS=2`, `ALL_2MM_PACKETS=38`; steady-state packets were all
  2 mm sentinel values.
- Report gate:

```text
gate = pipe_attr_zero_after_switch
```

Conclusion:

- The official calibration-style `RAW16 + NONE` dump route does not solve GS1860 near
  depth on this board setup. It only changes the buffer shape after startup; the
  measurement rows become zero after the switch.
- This rules out a useful class of "ask VI for uncompressed RAW16" bypasses unless a
  different official API is identified.
- The current route remains unchanged:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

- Avoid repeating RAW10/NONE, RAW12/NONE, or RAW16/NONE switch tests unless a new
  hypothesis changes more than bit width and compression mode. The only known stream
  carrying stable GS1860 payload is still the original `RAW12 + LINE` buffer.

Safety note: this RAW16 after-start diagnostic was perception-only. No actuator, MCU
bridge, CAN, serial actuator, motor, steering, brake, or throttle process was started.

## 25. 2026-06-02 RAW12+LINE row-pattern analysis

After PIPE and FE_OUT both returned the same `RAW12 + LINE` buffer, an offline pattern
analysis was added so the line-compression evidence is reproducible without rerunning the
board.

Tooling changes:

- Added `tools/analyze_dtof_line_compress_patterns.py` to inspect saved
  `dtof_line_dump_f*.bin` buffers for common row hashes, mask-like word sequences, and
  ordinary RAW10/RAW12/RAW16 unpack feasibility.
- Updated `tools/dtof_phase1_log_report.py` to report `line_stride_mismatches` when a
  compressed line cannot contain the ordinary unpack width for its pixel format.
- Regenerated the PIPE, FE_OUT, BAS, and original line-dump JSON reports.
- Updated `logs/dtof_phase1_suite_status_latest.json` and
  `logs/dtof_phase1_suite_compare_latest.json`.

Run commands:

```powershell
.venv\Scripts\python tools\analyze_dtof_line_compress_patterns.py artifacts\dtof_line_dump_cp_20260602_124450 --out artifacts\dtof_line_dump_cp_20260602_124450\line_compress_pattern_analysis.json
.venv\Scripts\python tools\analyze_dtof_line_compress_patterns.py artifacts\dtof_line_dump_feout_cp_20260602_125819 --out artifacts\dtof_line_dump_feout_cp_20260602_125819\line_compress_pattern_analysis.json
```

Artifacts:

- `artifacts/dtof_line_dump_cp_20260602_124450/line_compress_pattern_analysis.json`
- `artifacts/dtof_line_dump_feout_cp_20260602_125819/line_compress_pattern_analysis.json`
- `logs/dtof_phase1_near30cm_line_dump_cp_official_20260602_124450_report.json`
- `logs/dtof_phase1_near30cm_line_dump_feout_cp_official_20260602_125819_report.json`
- `logs/dtof_phase1_suite_status_latest.json`
- `logs/dtof_phase1_suite_compare_latest.json`

Pattern result:

- PIPE and FE_OUT analyses are identical.
- Across 4 frames, there are 120 measurement rows. A single measurement-row hash
  appears in 117 rows; only 3 rows differ.
- The common measurement row has 342 nonzero bytes, ending at byte 343 of a
  3552-byte stride.
- The first 344 bytes are dominated by 32-bit words with exactly one cleared bit:
  79 of 86 words match that pattern, ratio `0.9186`.
- Ordinary stride-local unpacking does not produce a dense `40 * 64` histogram row:
  RAW10 yields only 5 nonzero 64-bin groups; RAW12 yields only 4; RAW16 yields only 3.
- For the observed `pixfmt=21`, `compress=4`, `width=2560`, and `stride0=3552`,
  ordinary RAW12 unpack would need `2560 * 12 / 8 = 3840` bytes per row. That is
  larger than the line stride, so treating this buffer as ordinary RAW12 crosses the
  line boundary before it can decode one logical row.

Updated report classification note:

```text
RAW12+LINE bytes are present, but ordinary raw unpack produces sparse sentinel/far output.
LINE-compressed pixfmt=21 width=2560 needs 3840 ordinary bytes/row, but stride0=3552; ordinary unpack would cross the line boundary.
```

Conclusion:

- This is now a stronger software-side root-cause marker than the earlier generic
  "sparse raw" observation. The saved buffers are not ordinary RAW12 frames.
- The current user-space `deal_frame_data()` path is structurally wrong for
  `OT_COMPRESS_MODE_LINE` because it attempts an ordinary RAW12-style expansion of a
  line-compressed stream.
- The current route remains:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

- The next meaningful technical action is to obtain the SS928/HiSilicon RAW line
  compression format or an official decompressed-frame API. Without that, a custom
  decoder must first prove it can turn these saved buffers into a dense
  `30 * 40 * 64` histogram that makes `DtofProcess()` output mostly `<1 m` under the
  near obstruction.

Safety note: this row-pattern analysis was local/offline only. No board-side sample,
actuator, MCU bridge, CAN, serial actuator, motor, steering, brake, or throttle process
was started.

## 26. 2026-06-02 ADVANCED RAW12/NONE startup control

Motivation:

- The earlier RAW12/NONE startup binary failed while using the normal VI video mode.
- The official `sample_dtof_get_default_vb_config()` path selects
  `OT_COMPRESS_MODE_LINE` in `OT_VI_VIDEO_MODE_NORM`, but uses `OT_COMPRESS_MODE_NONE`
  otherwise. A bounded control test was added to change the VI video mode to
  `OT_VI_VIDEO_MODE_ADVANCED` and request `RAW12 + NONE` from startup.
- This was a directed test of a possible official decompressed-frame bypass, not a new
  random RAW format sweep.

Build and deploy:

- Build script: `tools/vm_build_official_advanced_raw12_start.sh`
- VM build directory:
  `/home/ebaina/official_dtof_advanced_raw12_start_20260602_132531`
- VM binary:
  `/home/ebaina/official_dtof_advanced_raw12_start_20260602_132531/src/dtof/sample_dtof_official_advanced_raw12_start_dbg`
- Board binary:
  `/opt/sample/official_dtof/sample_dtof_official_advanced_raw12_start_dbg`
- SHA256:

```text
68635f3c7c84040d8279efdb2f38d9448bc027e1ec60e5a6e63d172b4c78bc84
```

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_advanced_raw12_start_official --binary sample_dtof_official_advanced_raw12_start_dbg --seconds 20 --max-packets 60
```

Logs and reports:

- `logs/dtof_phase1_near30cm_advanced_raw12_start_official_20260602_132657_commands.txt`
- `logs/dtof_phase1_near30cm_advanced_raw12_start_official_20260602_132657_board.log`
- `logs/dtof_phase1_near30cm_advanced_raw12_start_official_20260602_132657_vm.log`
- `logs/dtof_phase1_near30cm_advanced_raw12_start_official_20260602_132657_report.json`
- `logs/dtof_phase1_suite_status_latest.json`
- `logs/dtof_phase1_suite_compare_latest.json`

Result:

- The stream did start as `RAW12 + NONE`:
  `w=2560`, `h=31`, `stride0=3840`, `pixfmt=21`, `compress=0`.
- The measurement rows were zero from the first frame:
  `row_sum32=1052/0/0`, `row1_first16` all zero, `raw_nonzero=0`, and
  `raw_max=0` for all 12 debug frames.
- DToF output stayed at the 2 mm sentinel:
  `out_max=2`, `out_mid=2`, `out_eq_2=1200` for all debug frames.
- UDP transport still passed official packet-format checks:
  `PACKETS=60`, `GOOD_SIZE_4873=60`, `GOOD_HEADER_40x30=60`.
- VM depth validation failed:
  `VALIDISH_DEPTH_PACKETS=0`, `ALL_2MM_PACKETS=60`.
- Report gate:

```text
gate = raw_zero_from_start
```

Conclusion:

- `OT_VI_VIDEO_MODE_ADVANCED + RAW12/NONE` does not provide a valid decompressed GS1860
  raw stream on this board setup.
- This closes another "ask VI for uncompressed raw from startup" bypass. The only known
  stream carrying stable GS1860 payload remains `RAW12 + LINE`.
- The current route remains:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

- Avoid further RAW10/NONE, RAW12/NONE, or RAW16/NONE toggles unless a new API or
  control variable beyond bit width, compression mode, and video mode is identified.
- The next meaningful work is to obtain the SS928/HiSilicon RAW line-compression format
  or an official decompressed-frame API. If that is not available, collect controlled
  `RAW12 + LINE` dumps under known physical conditions and build a decoder that proves it
  can produce the required `30 * 40 * 64` uint16 histogram for `DtofProcess()`.

Safety note: this ADVANCED RAW12/NONE diagnostic was perception-only. No actuator, MCU
bridge, CAN, serial actuator, motor, steering, brake, or throttle process was started.

## 27. 2026-06-02 safety postcheck after ADVANCED RAW12/NONE test

Read-only postcheck commands:

```powershell
.venv\Scripts\python tools\board_run.py "ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true"
.venv\Scripts\python tools\board_run.py "lsmod | grep -E 'ot_mipi_rx|ot_isp|ot_vi|ot_base' || true"
.venv\Scripts\python tools\vm_ssh_run.py run "ss -lunp | grep ':2368' || true"
.venv\Scripts\python tools\vm_ssh_run.py run "ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result:

- Board process grep returned no matching process.
- VM UDP port `2368` had no listener after the test.
- VM process grep returned no matching process.
- Board media modules were loaded (`ot_mipi_rx`, `ot_isp`, `ot_vi`, `ot_base`) but not
  held by a running `sample_dtof` process.

Safety conclusion: no actuator, MCU bridge, CAN, serial actuator, motor, steering,
brake, throttle, RTSP, or dToF sample process was left running after the diagnostic.

## 28. 2026-06-02 RAW12+LINE symbol scan and mask heuristic control

This round continued the current route:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

### 28.1 SDK/library symbol scan

Added `tools/vm_scan_dtof_line_symbols.sh` and ran it on the VM SDK copy at:

```text
/home/ebaina/official_dtof_raw16_afterstart_debug_20260602
```

Result:

- `libss_mpi.so` exports the known raw/compression-related APIs:
  `ss_mpi_sys_set_raw_frame_compress_param`,
  `ss_mpi_sys_get_raw_frame_compress_param`,
  `ss_mpi_vi_get_pipe_compress_param`, and `ss_mpi_vi_send_pipe_raw`.
- No exported or string-visible user-space raw-line decompressor was found in
  `libss_mpi.so`, `libss_isp.so`, `libss_tde.so`, or `libss_mcf_vi.so`.
- This supports the earlier conclusion that the SDK exposes compression metadata and
  compressed frames, but not an obvious user-space `OT_COMPRESS_MODE_LINE` decompressor.

### 28.2 40x64 mask hypothesis

Added `tools/analyze_dtof_line_mask_hypothesis.py` and generated:

- `artifacts/dtof_line_dump_cp_20260602_124450/line_mask_hypothesis_analysis.json`
- `artifacts/dtof_line_dump_feout_cp_20260602_125819/line_mask_hypothesis_analysis.json`

Offline result:

- PIPE and FE_OUT match.
- The best candidate mask segment starts at word 4 in all analyzed frames.
- The segment length is 80 words, exactly `40 * (64 / 32)`.
- For each measurement row, this maps structurally to `40` pixels by `64` histogram
  bins if one cleared bit marks an active bin in each 32-bin half.
- The common row signature is stable across rows and frames. This is useful as a
  structural clue, but it also means the simple mask segment alone is not sufficient
  evidence of real near-target response.

### 28.3 mask heuristic board tests

Added:

- `tools/vm_build_official_line_mask_heuristic.sh`
- `tools/dtof_phase1_log_report.py` parsing for `[DTOF_MASK]`
- `tools/dtof_phase1_compare_reports.py` compare notes for
  `line_mask_heuristic_far_not_near`

The first binary, `sample_dtof_official_line_mask4095_dbg`, built and deployed with:

```text
SHA256=40ca152361b358375c3c220f5ebac89b4e5d40c64c999f6fca3622b19ed131ad
```

It did not contain the expected `[DTOF_MASK]` string in the final binary, so the mask
branch did not execute. Its test is retained as a negative control:

- `logs/dtof_phase1_near30cm_line_mask4095_official_20260602_134124_board.log`
- `logs/dtof_phase1_near30cm_line_mask4095_official_20260602_134124_vm.log`
- `logs/dtof_phase1_near30cm_line_mask4095_official_20260602_134124_report.json`

The corrected v2 binary, `sample_dtof_official_line_mask4095_v2_dbg`, explicitly enables
the heuristic in source and was verified by `strings` before deployment:

```text
SHA256=7e0acb3d43004bb46e3495becba17cb062342d5948c001d700e2daa99e99fb27
```

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_line_mask4095_v2_official --binary sample_dtof_official_line_mask4095_v2_dbg --seconds 20 --max-packets 60
```

Logs:

- `logs/dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_commands.txt`
- `logs/dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_board.log`
- `logs/dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_vm.log`
- `logs/dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_report.json`
- `logs/dtof_phase1_suite_status_latest.json`
- `logs/dtof_phase1_suite_compare_latest.json`

v2 result:

- The heuristic branch executed:

```text
[DTOF_MASK] decoded_rows=30 active_bins=2340 amplitude=4095 pixfmt=21 compress=4 stride0=3552
```

- It removed the 2 mm sentinel, but produced stable far depth:
  `out_eq_2=0`, `out_mid=6661`, `out_max=8207`.
- UDP transport remained valid:
  `PACKETS=60`, `GOOD_SIZE_4873=60`, `GOOD_HEADER_40x30=60`.
- UDP depth was not near:
  `VALIDISH_DEPTH_PACKETS=60`, `ALL_2MM_PACKETS=0`,
  `depth_mean_median=5985.3`, `depth_max_median=8207`.
- Report gate:

```text
gate = line_mask_heuristic_far_not_near
```

Conclusion:

- The 80-word segment is a useful structural clue because it maps exactly to
  `40 * 64` bins, but the simple interpretation "one cleared bit is the active peak;
  use amplitude 4095" is not a valid dToF near-depth decoder.
- This is still progress: the branch proves `DtofProcess()` can be driven away from
  the 2 mm sentinel by a reconstructed histogram, but the reconstruction semantics are
  wrong and produce far depth around 6 m.
- Do not use the mask heuristic as a fix, and do not tune ROS thresholds around it.
- The next meaningful step is still one of:
  1. obtain the SS928/HiSilicon RAW line-compression format or decompressor API; or
  2. collect controlled `RAW12 + LINE` dumps under known physical conditions
     (`clear`, `near30cm`, `covered/dark`) to identify which bytes actually change with
     scene depth and which bytes are compression structure/header.

Safety note: these tests were perception-only. They started only board-side dToF sample
and VM UDP capture. No actuator, MCU bridge, CAN, serial actuator, motor, steering,
brake, or throttle process was started.

## 29. 2026-06-02 post-test safety and idle-state check

After the line-mask heuristic tests, the board and VM were checked for lingering
dToF, streaming, parking perception, or actuator-related processes.

Board process check:

```powershell
.venv\Scripts\python tools\board_run.py "ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true"
```

Result: no matching process remained on the board.

Board media module check:

```powershell
.venv\Scripts\python tools\board_run.py "lsmod | grep -E 'ot_mipi_rx|ot_isp|ot_vi|ot_base' || true"
```

Result: the media kernel modules were still loaded (`ot_mipi_rx`, `ot_isp`,
`ot_vi`, `ot_base`, `ot_osal`), but no sample process was holding them.

VM UDP listener check:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "ss -lunp | grep ':2368' || true"
```

Result: no UDP 2368 listener remained on the VM.

VM process check:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result: no matching process remained on the VM.

Safety conclusion:

- The vehicle did not move during these checks or the preceding dToF tests.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, or throttle
  software was started.
- The latest dToF result is still not accepted as a fix: the v2 mask heuristic
  generates valid 4873-byte UDP packets but reports far depth under near obstruction.

## 30. 2026-06-02 controlled RAW12+LINE condition capture tooling

The current route still requires decoding or bypassing `RAW12 + LINE` compression before
feeding `DtofProcess()`:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

This round added tooling for the next controlled physical-condition test instead of
continuing random RAW bit-width or compression toggles.

### 30.1 New tools

Added `tools/capture_dtof_line_condition.py`.

Purpose:

- Run the perception-only line-dump sample through `tools/run_dtof_phase1_condition.py`.
- Download board-side `dtof_line_dump_f*.bin` and `dtof_line_dump_f*.meta` from
  `/opt/sample/official_dtof` into a timestamped `artifacts/dtof_line_dump_<condition>_*`
  directory.
- Immediately run:
  - `tools/analyze_dtof_line_dump.py`
  - `tools/analyze_dtof_line_mask_hypothesis.py`

The wrapper does not start any MCU bridge, CAN actuator, serial actuator, motor,
steering, brake, or throttle program. It starts only the dToF sample and VM UDP listener.
It also does not delete board files; it only downloads the dump files written by the
sample.

Example commands for the required physical-condition sequence:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition near30cm --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition covered_dark --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

These commands require user-controlled physical setup before each run:

- `clear`: remove close obstruction from the dToF field of view.
- `near30cm`: place a flat obstruction within 30 cm in the dToF field of view.
- `covered_dark`: cover or dark-block the dToF aperture to suppress returns.

Added `tools/compare_dtof_line_conditions.py`.

Purpose:

- Compare two or more downloaded RAW12+LINE artifact directories.
- Report per-condition metadata, row hash stability, mask-segment signatures, and
  condition-dependent byte/word offsets.
- Pairwise report fields include:
  - `mode_row_changed_byte_offsets`
  - `mode_row_changed_word_offsets`
  - `top_byte_offsets`
  - `top_word_offsets`
  - `mask_active_bin_delta_top`

Example comparison command after the three captures:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py clear=artifacts\<clear_dir> near30cm=artifacts\<near_dir> covered_dark=artifacts\<covered_dir> --out artifacts\dtof_line_conditions_compare_<timestamp>.json
```

### 30.2 Tool validation with existing PIPE/FE_OUT dumps

The comparator was validated against the existing PIPE and FE_OUT near-obstruction
artifacts:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py cp=artifacts\dtof_line_dump_cp_20260602_124450 feout=artifacts\dtof_line_dump_feout_cp_20260602_125819 --out artifacts\dtof_line_dump_cp_vs_feout_compare_20260602.json
```

Result:

```text
mode_row_changed_byte_offsets = 0
mode_row_changed_word_offsets = 0
mask_active_bin_delta_top = []
```

Interpretation:

- This is the expected negative control because previous analysis showed PIPE and FE_OUT
  dumps are byte-identical for the saved frames.
- The comparator is therefore suitable for the next three-condition physical test. A
  real clear-vs-near-vs-covered comparison should expose offsets that change with the
  optical scene. If it does not, the next suspect is physical light path, trigger/config,
  power, or MIPI mapping rather than ROS-side thresholds.

### 30.3 Read-only state check before physical captures

Read-only board command:

```powershell
.venv\Scripts\python tools\board_run.py "hostname; pwd; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true; lsmod | grep -E 'ot_mipi_rx|ot_isp|ot_vi|ot_base' || true; cd /opt/sample/official_dtof && sha256sum sample_dtof_official_line_dump_cp_dbg sample_dtof_official_line_mask4095_v2_dbg 2>/dev/null || true"
```

Result:

- No matching board `sample_dtof`, RTSP, perception, MCU, CAN, serial actuator, motor,
  steering, brake, or throttle process was found.
- Media modules were loaded but idle: `ot_mipi_rx`, `ot_isp`, `ot_vi`, `ot_base`,
  `ot_osal`.
- Board binary hashes:

```text
3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea  sample_dtof_official_line_dump_cp_dbg
7e0acb3d43004bb46e3495becba17cb062342d5948c001d700e2daa99e99fb27  sample_dtof_official_line_mask4095_v2_dbg
```

Read-only VM command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "hostname; ss -lunp | grep ':2368' || true; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result:

- VM host is `ebaina-virtual-machine`.
- No UDP `2368` listener remained.
- No matching VM dToF, RTSP, perception, MCU bridge, STM32, CAN, serial actuator,
  motor, steering, brake, throttle, or actuator process was found.

### 30.4 SDK clue retained

The local SDK still does not expose an obvious user-space decompressor for
`OT_COMPRESS_MODE_LINE`, but `ot_buffer.h` confirms the line-compressed raw buffer sizing
formula:

```text
raw_compress_ratio = 1538 for OT_COMPRESS_MODE_LINE
stride = align(((16 + width * bit_width * 1000 / 1538 + 8192 + 127) / 128 aligned to 2) * 16)
```

For the observed GS1860 dump metadata (`width=2560`, RAW12, `height=31`), this explains
the `stride0=3552` line-compressed buffer shape. It does not provide the decompression
semantics; the next evidence must come from controlled scene-dependent dumps or from an
official raw line-compression format/API.

## 31. 2026-06-02 DtofProcess input contract and depth library symbol check

The latest code and binary inspection narrows the failure point further: the official
`DtofProcess()` path expects an already expanded histogram buffer, but the current
`RAW12 + LINE` capture path is still handing it line-compressed bytes through an ordinary
RAW12 unpacking routine.

### 31.1 Source-side evidence

`DataProc.h` defines the dToF processing input as:

```c
unsigned short* data;
unsigned int dataLen;
```

The official sample populates this as a `30 * 40 * 64` histogram before calling
`DtofProcess()`.

The `deal_frame_data()` path in `dtof_dumpraw.c` still uses an ordinary RAW unpack
sequence:

- Skip the first VI row as a header row.
- For each of the remaining 30 rows, expand to `video_frame->width` 16-bit values.
- Set `handle->dataLen = 30 * 40 * 64`.

That is structurally inconsistent with the observed `RAW12 + LINE` frame shape:

```text
pixfmt=21 compress=4 stride0=3552 width=2560 height=31
```

Ordinary RAW12 unpacking needs `2560 * 12 / 8 = 3840` bytes per row. The actual
line-compressed stride is only 3552 bytes, so the current ordinary unpack overreads each
row by 288 bytes and mixes row data. This explains why raw values can be nonzero while
`DtofProcess()` still produces 2 mm sentinels or far-distance output under a close
obstruction.

### 31.2 `libdepth_process.a` symbol scan

Added `tools/vm_depth_process_symbols.sh` and ran it on the VM SDK copy. Log:

```text
logs/vm_ssh_20260602_140345_4534fb4d.log
```

The scan found the expected dToF histogram-processing symbols:

```text
DtofProcess
DtofInit
DtofDestory
Dtof::Processor::Process(unsigned short const*, int, float const&)
Dtof::HistoProc::Run(unsigned short const*, int, unsigned short const*, int, std::vector<Dtof::EchoInfo...>&, int const&, int const&)
Dtof::HistoInfo::GetHistoSize()
Dtof::HistoInfo::GetHistoNum()
Dtof::PileUp::ConfigSwitch(bool const&)
Dtof::PileUp::GetFactorPs()
Dtof::PileUp::GetTdcTimeBin(unsigned short&) const
Dtof::PileUp::GetTotalShotNum(unsigned int&) const
LoadHistoData
UdpSendTofData
```

No user-space RAW line decompressor symbol was found in the depth library. Combined with
the function signatures above, this indicates that `libdepth_process.a` is the histogram
processor, not the missing MIPI `OT_COMPRESS_MODE_LINE` decompressor.

### 31.3 Config and documentation notes

`dtof.ini` still matches the expected official 40x30 histogram shape:

```text
spadWidth=40
spadHeight=30
binNum=64
validBinNum=62
shotNumDesignNum=1024
configSwitchFlag=false
tdcTimeBinNear=500
tdcTimeBinFar=1000
totalShotNumNear=30000
totalShotNumFar=30000
```

The official README only identifies `SAVE_DTOF_DATA` as a way to save TOF output data; it
does not document the compressed raw-line layout or a raw decompression API. The GS1860
module documentation states that the module range includes near distances around 0.1 m,
so a 30 cm obstruction should be physically valid if the optical path and raw decode are
correct.

### 31.4 Current conclusion

Current decision remains:

```text
decode_or_bypass_raw12_line_compression_before_dtofprocess
```

The next useful evidence is not another random RAW10/RAW12/NONE/LINE toggle. It is the
controlled physical-condition dump sequence:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition near30cm --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition covered_dark --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Those captures should identify which byte/word offsets inside the compressed line data
actually change with the optical scene. If clear, near, and covered-dark dumps do not
show scene-dependent raw changes, the next suspect shifts to physical light path,
trigger/config, power, J3/J4 wiring, or MIPI mapping rather than software thresholds.

Safety status for this step:

- No board sample was started.
- No UDP listener was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.
- The only VM-side non-read-only action was uploading a temporary symbol-scan script to
  `/tmp` and running it for static SDK inspection.

## 32. 2026-06-02 condition comparator hardening and idle-state refresh

This step did not start any dToF sample and did not require any physical movement. It
focused on making the next clear/near/covered physical-condition comparison harder to
misread.

### 32.1 SDK/header confirmation

The public SS928 headers still expose the compression parameter as an opaque byte array:

```c
typedef struct {
    td_u8 compress_param[OT_VI_COMPRESS_PARAM_SIZE];
} ot_vi_compress_param;
```

`OT_VI_COMPRESS_PARAM_SIZE` is `152`. No public C header or sample source in the local
official SDK provides a user-space `OT_COMPRESS_MODE_LINE` decompressor. The exposed APIs
remain:

```text
ss_mpi_vi_get_pipe_compress_param()
ss_mpi_sys_set_raw_frame_compress_param()
ss_mpi_sys_get_raw_frame_compress_param()
```

### 32.2 Comparator improvement

Updated `tools/compare_dtof_line_conditions.py`:

- Preserve the full aggregate active-bin count map, not only `most_common(32)`.
- Still emit `aggregate_active_bin_counts_top` for compact reading.
- Add `compress_param` summary per condition:
  - byte size, SHA, nonzero count, byte sum
  - full little-endian `u32` word list
  - first 32 little-endian `u16` words
  - candidate known fields

The candidate field extraction on the existing PIPE dump identifies:

```text
word7_width = 2560
word8_height = 31
word28_ordinary_raw10_bytes_per_row = 2048
word33_aligned_delta_a = 384
word34_aligned_delta_b = 384
word35_raw12_stride_deficit = 288
```

`word35 = 288` is notable because ordinary RAW12 row bytes for `width=2560` are
`3840`, while the actual line-compressed stride is `3552`; the difference is exactly
`288` bytes.

### 32.3 Negative-control validation

Re-ran the existing PIPE-vs-FE_OUT comparison:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py cp=artifacts\dtof_line_dump_cp_20260602_124450 feout=artifacts\dtof_line_dump_feout_cp_20260602_125819 --out artifacts\dtof_line_dump_cp_vs_feout_compare_20260602.json
```

Result remains the expected negative control:

```text
mode_row_changed_byte_offsets = 0
mode_row_changed_word_offsets = 0
mask_active_bin_delta_top = []
compress_param.sha256 = 647057ba5f7082a05286f32fd737c0c005586a032bbe3f84e8427213b95e0c9a
```

Interpretation:

- PIPE and FE_OUT still return identical saved compressed rows for this dToF path.
- The comparator changes did not disturb the prior route decision.
- The next useful input remains real condition-dependent data: `clear`, `near30cm`, and
  `covered_dark`.

### 32.4 Local syntax check

Ran:

```powershell
.venv\Scripts\python -m py_compile tools\compare_dtof_line_conditions.py tools\capture_dtof_line_condition.py tools\analyze_dtof_line_dump.py tools\analyze_dtof_line_compress_patterns.py tools\analyze_dtof_line_mask_hypothesis.py
```

Result: all listed Python tools compiled successfully.

### 32.5 Board and VM idle-state refresh

Read-only board command:

```powershell
.venv\Scripts\python tools\board_run.py "hostname; pwd; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true; lsmod | grep -E 'ot_mipi_rx|ot_isp|ot_vi|ot_base' || true; cd /opt/sample/official_dtof && sha256sum sample_dtof_official_line_dump_cp_dbg sample_dtof_official_line_mask4095_v2_dbg 2>/dev/null || true"
```

Result:

- No matching board `sample_dtof`, RTSP, perception, MCU, CAN, serial actuator, motor,
  steering, brake, or throttle process was found.
- Media modules were loaded but no user sample was running.
- Board binary hashes remained:

```text
3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea  sample_dtof_official_line_dump_cp_dbg
7e0acb3d43004bb46e3495becba17cb062342d5948c001d700e2daa99e99fb27  sample_dtof_official_line_mask4095_v2_dbg
```

Read-only VM command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "hostname; ss -lunp | grep ':2368' || true; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result:

- VM host is `ebaina-virtual-machine`.
- No UDP `2368` listener remained.
- No matching VM dToF, RTSP, perception, MCU bridge, STM32, CAN, serial actuator,
  motor, steering, brake, throttle, or actuator process was found.

Safety status:

- No board sample was started in this step.
- No VM UDP listener was started in this step.
- No actuator, chassis, MCU bridge, CAN, serial actuator, motor, steering, brake, or
  throttle process was started.

## 33. 2026-06-02 all-existing dump comparison and capture stale-file guard

This step used only existing local artifacts and source/binary inspection. It did not
start a board sample, UDP listener, ROS process, RTSP process, MCU bridge, CAN actuator,
serial actuator, motor, steering, brake, or throttle process.

### 33.1 Three existing RAW12+LINE artifacts compared

Ran:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py dump124100=artifacts\dtof_line_dump_20260602_124100 cp=artifacts\dtof_line_dump_cp_20260602_124450 feout=artifacts\dtof_line_dump_feout_cp_20260602_125819 --out artifacts\dtof_line_dump_all_existing_compare_20260602.json
```

Summary:

```text
dump124100 vs cp:    mode_row_changed_byte_offsets=0, mode_row_changed_word_offsets=0, mask_active_bin_delta_top=0
dump124100 vs feout: mode_row_changed_byte_offsets=0, mode_row_changed_word_offsets=0, mask_active_bin_delta_top=0
cp vs feout:         mode_row_changed_byte_offsets=0, mode_row_changed_word_offsets=0, mask_active_bin_delta_top=0
```

Each condition had 4 frames and 120 measurement rows. The dominant measurement-row hash
was identical:

```text
ffee246e133657fa: 117 rows
6b5a6556669c37ee: 1 row
```

`dtof_line_dump_20260602_124100` did not include `compress_param_hex`, but its frame
shape matched:

```text
width=2560
height=31
stride0=3552
pixel_format=21
compress_mode=4
size=110112
```

Interpretation:

- All existing RAW12+LINE dumps currently available are byte-identical at the per-row
  mode level.
- They cannot reveal a scene-dependent raw payload by themselves.
- The next decisive evidence still requires controlled physical-condition captures:
  `clear`, `near30cm`, and `covered_dark`.

### 33.2 Local source and binary search result

Expanded local read-only search across official SDK sources, open_camera sources, MPP
libraries, and extracted kernel modules.

Text-source result:

- Many samples set the default raw pool to `RAW12 + LINE`.
- Public headers expose only opaque compression parameters and setup/query APIs:

```text
ot_vi_compress_param.compress_param[152]
ss_mpi_vi_get_pipe_compress_param()
ss_mpi_sys_set_raw_frame_compress_param()
ss_mpi_sys_get_raw_frame_compress_param()
ss_mpi_vi_send_pipe_raw()
```

Binary-string result:

- `libss_mpi.so` exports the same public VI/system APIs but no user-space raw-line
  decompressor symbol.
- `ot_vi.ko` contains hardware-path symbols such as:

```text
vi_drv_get_pipe_compress_param
vi_hal_viproc_set_out_y_compress_param
vi_hal_viproc_set_out_c_compress_param
vi_hal_viproc_set_out_compress_cfg
vi_hal_viproc_set_out_compress_en
vi_hal_viproc_set_cur_decompress_cfg
vi_hal_viproc_set_wdr_decompress_param
vi_hal_viproc_set_rref2_decompress_param
```

- `ot_tde.ko` contains TDE surface compression/decompression symbols, but no evidence
  that it is a user-space RAW12+LINE histogram decompressor for the GS1860 dToF pipe.
- `libdepth_process.a` still shows histogram-processing symbols (`HistoProc`,
  `Processor`, `DtofProcess`, `LoadHistoData`) and no raw-line decompressor.

Interpretation:

- The visible decompression support appears to live inside hardware/kernel paths, not in
  a public user-space function that can be called before `DtofProcess()`.
- Without an official line-compression format/API, the practical next options remain:
  1. derive the relevant compressed payload layout from controlled scene-dependent dumps,
     or
  2. find a VI path that yields a genuine decompressed GS1860 histogram/raw buffer before
     calling `DtofProcess()`.

### 33.3 Capture stale-file guard

Updated `tools/capture_dtof_line_condition.py` to avoid mistaking old board dump files
for new captures.

New behavior:

- Before starting `tools/run_dtof_phase1_condition.py`, the wrapper records the remote
  `/opt/sample/official_dtof/dtof_line_dump_f*.bin/.meta` file sizes and mtimes over
  SFTP.
- After the run, it downloads only dump files that are new or whose size/mtime changed.
- Unchanged remote files are reported as:

```text
SKIPPED_UNCHANGED_REMOTE_FILES=...
```

- `capture_manifest.txt` now records `remote_files_before`.

This does not delete board files and does not change board configuration. It only
prevents stale artifacts from polluting the clear/near/covered evidence sequence.

Local syntax check:

```powershell
.venv\Scripts\python -m py_compile tools\capture_dtof_line_condition.py tools\compare_dtof_line_conditions.py
```

Result: both scripts compiled successfully.

### 33.4 Next required physical-condition command

When the user confirms the dToF field of view is clear, run:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Purpose:

- Capture a clean `clear` baseline for the RAW12+LINE stream.
- Download only newly written board dumps.
- Run single-condition row analysis and mask-hypothesis analysis.

Risk:

- Starts only the board dToF sample and VM UDP listener.
- Does not start any actuator, chassis, MCU bridge, CAN, serial actuator, motor,
  steering, brake, or throttle path.
- It changes board/VM runtime state and generates logs/artifacts, so it still requires
  the user-confirmed physical condition before execution.

## 34. 2026-06-02 capture runner safety hardening

This step tightened the host-side runner before the next physical-condition capture. It
did not start a board dToF sample and did not start a VM UDP listener except for the
read-only VM process check command listed below.

### 34.1 Runner argument guard

Updated `tools/run_dtof_phase1_condition.py`:

- `--binary` must match `sample_dtof[A-Za-z0-9_.-]*`.
- `--case` must be numeric.
- `--vm-ip` may contain only hostname/IP-safe characters.
- `--seconds` must be `1..300`.
- `--max-packets` must be `1..5000`.

Reason:

- The runner builds a board-side shell command that starts the selected dToF sample.
- Even though the planned command uses a known safe binary, the tool should reject path
  traversal, separators, and shell metacharacters before reaching `tools/board_run.py`.
- This further narrows the runner to perception-only `sample_dtof*` binaries.

Updated `tools/capture_dtof_line_condition.py` with the same argument guard before it
calls the runner or opens any board SFTP connection.

### 34.2 VM log pipe hardening

Updated `tools/run_dtof_phase1_condition.py` so the VM UDP checker writes directly to
the VM log file while it runs. The previous implementation kept VM stdout in a pipe and
read it only after the board sample exited. That is usually fine for short captures, but
it could block if future `--max-packets` values produce enough output.

New behavior:

- Start VM UDP checker with stdout/stderr directed to the VM log file.
- Start the board dToF sample.
- Wait for VM checker completion.
- Read the VM log file back for console visibility and report generation.

This makes longer captures safer without changing the board command.

### 34.3 Local validation

Syntax check:

```powershell
.venv\Scripts\python -m py_compile tools\run_dtof_phase1_condition.py tools\capture_dtof_line_condition.py
```

Result: both scripts compiled successfully.

Invalid-argument guard tests:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition invalid_guard --binary ..\bad --seconds 1 --max-packets 1
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition invalid_guard --binary ..\bad --seconds 1 --max-packets 1 --skip-run
```

Result:

```text
Invalid argument: --binary must be a sample_dtof* file name without path or shell characters
```

The rejection happens before any board sample, VM UDP listener, or board SFTP download is
started.

### 34.4 Idle-state refresh

Read-only board command:

```powershell
.venv\Scripts\python tools\board_run.py "hostname; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true"
```

Result:

- No matching board `sample_dtof`, RTSP, perception, MCU, actuator, CAN, serial
  actuator, motor, steering, brake, or throttle process was found.

Read-only VM command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "hostname; ss -lunp | grep ':2368' || true; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result:

- VM host is `ebaina-virtual-machine`.
- No UDP `2368` listener remained.
- No matching VM dToF, RTSP, perception, MCU bridge, STM32, CAN, serial actuator, motor,
  steering, brake, throttle, or actuator process was found.

Safety status:

- No board sample was started.
- No VM UDP listener was started by the capture runner.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.

### 34.5 Next required physical-condition command

When the user confirms the dToF field of view is clear:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Purpose:

- Capture the `clear` baseline for the controlled `clear / near30cm / covered_dark`
  RAW12+LINE comparison.
- Download only changed/new board dump files.
- Run line-dump and mask-hypothesis analysis.

Risk:

- Starts only the board dToF sample and VM UDP listener.
- Does not start any actuator, MCU bridge, CAN, serial actuator, motor, steering,
  brake, or throttle path.
- It still changes board/VM runtime state and therefore must wait for the user-confirmed
  physical condition.

## 35. 2026-06-02 UDP output parser and near-depth gate hardening

This step audited the output-side packet parser against the official module documentation
and ROS demo. It did not start a board dToF sample, did not start a VM UDP listener, and
did not touch any actuator or chassis-control path.

### 35.1 Official UDP layout confirmation

Checked:

```text
vendor/dtof_sensor_driver-master/doc/模组点云数据结构说明/UDP数据格式.md
vendor/dtof_sensor_driver-master/sample/ubuntu_pc/dtof_ros_demo_udp/src/dtof_client_node/src/dtof_client.hpp
vendor/dtof_sensor_driver-master/sample/ubuntu_pc/dtof_ros_demo_udp/src/dtof_client_node/src/dtof_client_node.cpp
```

Confirmed packet structure:

- Data payload size: `4873` bytes.
- Header size: `73` bytes.
- Frame size: `40 x 30`, `1200` pixels.
- Header fields: `checkSum`, `seqNum`, `startPixel`, `pixelNumber`,
  `timestampSeconds`, `timestampNanoSeconds`, `width`, `height`, `frameRate`,
  `version`, and `reserved[12]`.
- Pixel format: `short depth`, `unsigned char confidence`, `unsigned char flag`.

This matches the existing width/height offsets (`18`, `20`) and payload size, but the old
VM checker only validated size and width/height. That was enough for transport checks but
not enough for acceptance of a real near-depth result.

### 35.2 VM UDP checker changes

Updated `tools/vm_dtof_udp_check.py` to report:

- `GOOD_PIXEL_NUMBER_1200`
- `GOOD_START_PIXEL_0`
- `GOOD_FRAME_RATE_30`
- `SEQ_GAP_COUNT`
- `TIMESTAMP_BACKWARD_COUNT`
- `VALID_NON_SENTINEL_PACKETS`
- `NEAR_ANY_LT_1000_PACKETS`
- `NEAR_MAJORITY_LT_1000_PACKETS`
- `NEAR_MEDIAN_LT_1000_PACKETS`
- total 2mm sentinel pixels and negative-depth pixels
- per-packet `valid`, `valid_median`, `valid_lt1000`, center depth, and unsigned
  min/max diagnostics in `DEPTH_SUMMARY`

The legacy `DTOF_UDP_CHECK=PASS` remains a transport/shape check for compatibility.
A new `DTOF_UDP_STRICT_CHECK=PASS` requires all captured packets to match size,
`40x30`, `pixelNumber=1200`, `startPixel=0`, and `frameRate=30`.

### 35.3 Report gate changes

Updated `tools/dtof_phase1_log_report.py` so a paired board/VM report can classify a
candidate as:

```text
near_depth_candidate
```

only when VM UDP packets are official `4873-byte / 40x30` packets, contain non-2mm valid
depths, and at least half of the captured packets have majority/median valid depth below
`1000 mm`.

Sparse near pixels are not treated as success. If a capture contains some `<1m` pixels but
not a majority-depth near result, the report adds a note instead of declaring success.
Raw-zero failure gates still take priority; a capture with board raw zero from the first
frame is not accepted as a near-depth candidate.

### 35.4 Local validation

Syntax and generated remote-script validation:

```powershell
.venv\Scripts\python -m py_compile tools\vm_dtof_udp_check.py tools\dtof_phase1_log_report.py tools\run_dtof_phase1_condition.py tools\capture_dtof_line_condition.py
.venv\Scripts\python -c "import textwrap; from tools.vm_dtof_udp_check import build_remote_script; compile(textwrap.dedent(build_remote_script(1, 1)), '<vm_dtof_udp_check_remote>', 'exec'); print('remote-script-compile-ok')"
```

Result:

```text
remote-script-compile-ok
```

Compatibility regression using an existing paired log:

```powershell
.venv\Scripts\python tools\dtof_phase1_log_report.py --condition regression_line_mask4095_v2 --board-log logs\dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_board.log --vm-log logs\dtof_phase1_near30cm_line_mask4095_v2_official_20260602_134455_vm.log
```

Result: the report still classified that run as `line_mask_heuristic_far_not_near`.
The far-depth line-mask heuristic was not reclassified as a near-depth success.

Synthetic in-memory classification check:

```powershell
.venv\Scripts\python -c "from tools.dtof_phase1_log_report import classify; board={'raw_zero_first_frame':None,'startup_errors':[],'debug_frame_count':5,'raw_nonzero':{'median':2000},'out_eq_2':{'median':0},'compress_modes':[4],'line_stride_mismatches':[]}; vm={'kv':{'PACKETS':10,'GOOD_SIZE_4873':10,'GOOD_HEADER_40x30':10,'GOOD_PIXEL_NUMBER_1200':10,'VALID_NON_SENTINEL_PACKETS':10,'NEAR_MAJORITY_LT_1000_PACKETS':8,'NEAR_MEDIAN_LT_1000_PACKETS':8,'NEAR_ANY_LT_1000_PACKETS':9,'ALL_2MM_PACKETS':0},'depth_unique':{'median':100},'depth_mean':{'median':400}}; print(classify(board, vm))"
```

Result:

```text
{'gate': 'near_depth_candidate', 'notes': ['VM UDP reports official 4873-byte/40x30 packets whose non-2mm valid depths are mostly <1m.']}
```

Raw-zero priority check:

```powershell
.venv\Scripts\python -c "from tools.dtof_phase1_log_report import classify; vm={'kv':{'PACKETS':10,'GOOD_SIZE_4873':10,'GOOD_HEADER_40x30':10,'GOOD_PIXEL_NUMBER_1200':10,'VALID_NON_SENTINEL_PACKETS':10,'NEAR_MAJORITY_LT_1000_PACKETS':8,'NEAR_MEDIAN_LT_1000_PACKETS':8,'NEAR_ANY_LT_1000_PACKETS':9,'ALL_2MM_PACKETS':0},'depth_unique':{'median':100},'depth_mean':{'median':400}}; good_board={'raw_zero_first_frame':None,'startup_errors':[],'debug_frame_count':5,'raw_nonzero':{'median':2000},'out_eq_2':{'median':0},'compress_modes':[4],'line_stride_mismatches':[]}; zero_board=dict(good_board, raw_zero_first_frame=1); print(classify(good_board, vm)['gate']); print(classify(zero_board, vm)['gate'])"
```

Result:

```text
near_depth_candidate
raw_zero_from_start
```

### 35.5 Current conclusion

This does not fix the dToF raw/input path. It hardens the output-side evidence so the next
physical-condition capture cannot be accepted unless the VM really sees official packets
whose valid non-sentinel depths are mostly `<1m`.

The main technical root-cause direction is unchanged: ordinary RAW12 unpack is still
invalid for the current `RAW12 + LINE` stream (`pixfmt=21`, `compress=4`, `stride0=3552`)
because ordinary RAW12 would require `3840` bytes per row. The next useful capture remains
the controlled `clear / near30cm / covered_dark` RAW12+LINE comparison, starting with the
user-confirmed `clear` scene.

Safety status:

- No board dToF sample was started in this step.
- No VM UDP listener was started in this step.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.

## 36. 2026-06-02 RAW12+LINE source audit and v2 dump structure analysis

This step refreshed the idle state and tightened the RAW12+LINE evidence. It did not start
a board dToF sample, did not start a VM UDP listener, and did not start any actuator or
chassis-control path.

### 36.1 Idle-state refresh

Read-only board check:

```powershell
.venv\Scripts\python tools\board_run.py "hostname; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|mcu|actuator|can0|candump|cansend|serial_actuator|motor|steer|brake|throttle' | grep -v grep || true; lsmod | grep -E 'ot_mipi_rx|ot_isp|ot_vi|ot_base' || true"
```

Result:

- No matching board `sample_dtof`, RTSP, perception, MCU, actuator, CAN, serial actuator,
  motor, steering, brake, or throttle process was found.
- Media modules were loaded: `ot_mipi_rx`, `ot_isp`, `ot_vi`, `ot_base`.

Read-only VM check:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "hostname; ss -lunp | grep ':2368' || true; ps -ef | grep -E 'sample_dtof|rtsp|parking_sensor|parking_mcu_bridge|stm32|can0|candump|cansend|serial_actuator|motor|steering|brake|throttle|actuator' | grep -v grep || true"
```

Result:

- VM host was `ebaina-virtual-machine`.
- No UDP `2368` listener was found.
- No matching VM dToF, RTSP, perception, MCU bridge, STM32, CAN, serial actuator, motor,
  steering, brake, throttle, or actuator process was found.

### 36.2 Source audit

Relevant source/header findings:

- `src/dtof/sample_dtof.c` allocates the default raw VB pool as `RAW12 + LINE` unless
  `DTOF_FORCE_RAW10_NONE` or `DTOF_FORCE_RAW12_NONE` is compiled in.
- `src/common/sample_comm_vi.c` initializes VI pipe attr with
  `pixel_format=OT_PIXEL_FORMAT_RGB_BAYER_12BPP` and
  `compress_mode=OT_COMPRESS_MODE_LINE`.
- `include/hisilicon/ot_buffer.h` calculates LINE stride using
  `raw_compress_ratio=1538`; this explains the observed `stride0=3552`.
- `include/hisilicon/ot_common_vi.h` exposes `ot_vi_compress_param` only as an opaque
  byte array, and `ss_mpi_vi.h` exposes `ss_mpi_vi_get_pipe_compress_param()` but no
  matching set/decode API.
- `ss_mpi_sys_set/get_raw_frame_compress_param()` applies raw frame compression ratios,
  not a RAW LINE decompression path.
- TDE exposes `is_decompress` for 2D surface operations (`ss_tde_bit_blit`,
  `ss_tde_quick_copy`, etc.), not a VI raw Bayer / GS1860 histogram decompressor.

Conclusion: no public user-space API was found that converts the current
`OT_COMPRESS_MODE_LINE` VI raw frame into the ordinary `uint16[30][40][64]` histogram
expected by `DtofProcess()`.

### 36.3 RAW12/NONE bypass evidence

The existing `raw12_start` reports were reviewed instead of rerunning them:

```powershell
Get-ChildItem logs -Filter "dtof_phase1_*raw12*_report.json" | ...
```

Result summary:

- `near30cm_raw12_start_after_reload`
- `near30cm_raw12_start_no500_official`
- `near30cm_advanced_raw12_start_official`

All successful-start RAW12/NONE variants had:

- `pixfmt=21`
- `compress=0`
- `stride0=3840`
- `raw_nonzero` median `0`
- VM packets all 2mm
- report gate `raw_zero_from_start`

This rules out "start GS1860 as RAW12/NONE" as the immediate fix. It produces the right
uncompressed stride shape, but the payload disappears from frame 1.

### 36.4 LINE dump structure analysis v2

Updated `tools/analyze_dtof_line_compress_patterns.py` to report the best candidate
`40 x 64` mask segment and the payload capacity after that segment.

Commands:

```powershell
.venv\Scripts\python -m py_compile tools\analyze_dtof_line_compress_patterns.py
.venv\Scripts\python tools\analyze_dtof_line_compress_patterns.py artifacts\dtof_line_dump_20260602_124100 --out artifacts\dtof_line_dump_20260602_124100\line_compress_pattern_analysis_v2.json
.venv\Scripts\python tools\analyze_dtof_line_compress_patterns.py artifacts\dtof_line_dump_cp_20260602_124450 --out artifacts\dtof_line_dump_cp_20260602_124450\line_compress_pattern_analysis_v2.json
.venv\Scripts\python tools\analyze_dtof_line_compress_patterns.py artifacts\dtof_line_dump_feout_cp_20260602_125819 --out artifacts\dtof_line_dump_feout_cp_20260602_125819\line_compress_pattern_analysis_v2.json
```

Result across all three artifact directories:

```text
common_measurement_row_hash = ffee246e133657fa
common_measurement_rows = 117 / 120
common_measurement_row_nonzero_bytes = 342
best_mask_start_byte = 16
best_mask_end_byte = 336
best_mask_bytes = 320
nonzero_after_mask = 8 bytes
expanded_40x64_uint16_histogram_row_bytes = 5120
compressed_stride_bytes = 3552
```

Interpretation:

- The common measurement row is mostly a compact `40 * (64 / 32)` word mask-like segment,
  not an expanded histogram.
- Only 8 nonzero bytes appear after the best 320-byte mask segment in the common row.
- A single expanded `40x64` 16-bit histogram row would require `5120` bytes, which is
  larger than the entire compressed row stride.
- Therefore `deal_frame_data()` ordinary RAW12 unpack cannot be made correct by changing
  only bit width or stride math. The missing piece is either the vendor LINE decode
  algorithm/hardware path, or a validated reconstruction path from mask/payload into the
  exact `DtofProcess()` input contract.

### 36.5 Offline DtofProcess preparation note

Board-side line dump files still exist in `/opt/sample/official_dtof`, so an offline
`DtofProcess()` mask-sweep program is possible without starting VI/MIPI/UDP. However,
`DtofInit()` normally receives a 521-byte EEPROM calibration block via
`gs1860_read_eeprom()`, and no saved full 521-byte EEPROM dump was found in the local
artifacts. Existing UDP logs carry only the 12 float camera parameters.

For a trustworthy offline sweep, first build a narrow diagnostic that exports the exact
521-byte EEPROM block using the official `gs1860_read_eeprom()` path. Do not replace that
with zero-filled calibration except as a clearly marked low-confidence structural test.

Safety status:

- No board sample was started.
- No VM UDP listener was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.

## 37. 2026-06-02 EEPROM-only official-path diagnostic

This step built and ran a narrow official-baseline diagnostic to export the exact GS1860
EEPROM calibration block needed for trustworthy offline `DtofProcess()` experiments.

The diagnostic starts the official dToF sensor/VI path only far enough to call
`gs1860_read_eeprom()`. It then skips `vi_bayerdump()`, `DtofProcess()`, and UDP depth
output, exits through the official cleanup path, and does not touch any actuator or
chassis-control software.

### 37.1 Tooling added

New local tools:

```text
tools/vm_build_official_eeprom_dump.sh
tools/deploy_vm_binary_to_board_official.py
tools/run_dtof_eeprom_dump.py
tools/dtof_eeprom_log_extract.py
```

`tools/vm_build_official_eeprom_dump.sh` unpacks the official dToF source zip on the VM,
inserts an `EXTRA_CFLAGS` hook if the zip Makefile lacks one, builds with
`-DDTOF_EEPROM_DUMP_ONLY`, and emits a separate diagnostic binary named
`sample_dtof_official_eeprom_dump_dbg`.

`tools/deploy_vm_binary_to_board_official.py` copies a validated `sample_dtof*` binary
from the VM to `/opt/sample/official_dtof/`. The board did not support SFTP negotiation,
so the script used its SSH/base64 fallback for this deployment.

### 37.2 Build and deployment

VM build command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "bash /home/ebaina/vm_build_official_eeprom_dump.sh"
```

Result:

```text
BUILD_DIR=/home/ebaina/official_dtof_eeprom_dump_20260602_150217
BINARY=/home/ebaina/official_dtof_eeprom_dump_20260602_150217/src/dtof/sample_dtof_official_eeprom_dump_dbg
binary_sha256=b99a500f7f32a42dee7b6373dfb58a142813c6c366afe4beca02f9b16cee1d48
binary_size=4538288
```

Compile log confirmed `-DDTOF_EEPROM_DUMP_ONLY` was present for the dToF objects.

Deployment command:

```powershell
.venv\Scripts\python tools\deploy_vm_binary_to_board_official.py --vm-binary /home/ebaina/official_dtof_eeprom_dump_20260602_150217/src/dtof/sample_dtof_official_eeprom_dump_dbg
```

Result:

```text
BOARD_UPLOAD_METHOD=ssh_base64_fallback
/opt/sample/official_dtof/sample_dtof_official_eeprom_dump_dbg
board_binary_sha256=b99a500f7f32a42dee7b6373dfb58a142813c6c366afe4beca02f9b16cee1d48
mode=-rwxr-xr-x
```

### 37.3 EEPROM run

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_eeprom_dump.py --condition j4_eeprom_official --binary sample_dtof_official_eeprom_dump_dbg --case 2 --seconds 20
```

Artifacts:

```text
logs/dtof_eeprom_j4_eeprom_official_20260602_150702_commands.txt
logs/dtof_eeprom_j4_eeprom_official_20260602_150702_board.log
logs/dtof_eeprom_j4_eeprom_official_20260602_150702_board.extract_stdout.log
artifacts/dtof_eeprom_dtof_eeprom_j4_eeprom_official_20260602_150702_board_20260602_150704/gs1860_eeprom_521.bin
artifacts/dtof_eeprom_dtof_eeprom_j4_eeprom_official_20260602_150702_board_20260602_150704/gs1860_eeprom_521_report.json
```

Result:

```text
gs1860_read_eeprom_ret=0x0
eeprom_len=521
eeprom_nonzero=269
eeprom_byte_sum=33123
eeprom_sha256=c85a2140e390b9e6d2e3c4278ac2f3449a5202afff49c49afbb02df9e1788473
DTOF_EEPROM_RC=0
```

The first 64 bytes were:

```text
24 01 00 00 da 5b 17 42 27 e0 10 42 75 02 90 41
2a 3a 7a 41 fe 0f 40 3e b7 d1 a0 c0 4b 97 2a ba
c6 f6 bd ba e9 c8 8d 41 88 30 3c c4 b8 17 c2 bf
aa c5 90 3f af ea 8f bb 78 9f 4a bb 03 af 53 bc
```

Local parse sanity check:

```text
u32[0] = 0x124
float[1:9] = 37.839699, 36.218899, 18.001200, 15.639200,
             0.187561, -5.025600, -0.000651, -0.001449
ascii_run = AS01v1000240521c00007
```

This supports that the EEPROM content is a real calibration/manufacturing block, not a
random or zero-filled placeholder.

The board log also printed `[Func]:gs1860_exit [Line]:636 [Info]:gs1860 exit failed!`
before `linear mode`; the diagnostic still read EEPROM successfully and exited normally.
Treat that line as an initialization cleanup warning unless a later run shows it
correlates with capture failure.

### 37.4 Safety and conclusion

Read-only post-run check found no matching board `sample_dtof`, RTSP, perception, MCU,
actuator, CAN, serial actuator, motor, steering, brake, or throttle process.

Safety status:

- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.
- No VM UDP listener was started.
- No `DtofProcess()` or UDP depth output was run by the EEPROM-only diagnostic.
- The vehicle did not move.

Current conclusion:

- The full 521-byte GS1860 EEPROM calibration block is now available and should be used
  for any offline or semi-offline `DtofProcess()` experiment.
- Zero-filled or guessed calibration is no longer acceptable for primary conclusions.
- This does not yet fix near-distance output. It removes a missing-calibration blocker
  for the next controlled test: reconstruct or bypass the `RAW12 + LINE` compressed
  input into the exact `uint16[30][40][64]` histogram contract expected by
  `DtofProcess()`, then verify against the saved line dumps before running another
  physical-condition capture.

## 38. 2026-06-02 offline LINE mask sweep with real EEPROM

This step used the newly exported EEPROM block to build and run a board-side offline
`DtofProcess()` sweep. The test does not start sensors, VI/MIPI, `dtof_init.sh`, UDP, or
any actuator path. It only reads an existing saved `dtof_line_dump_f001.bin` file from
`/opt/sample/official_dtof` and calls `DtofProcess()` with generated histogram inputs.

### 38.1 Tooling added

New tools:

```text
tools/vm_build_official_offline_line_sweep.sh
tools/run_dtof_offline_line_sweep.py
```

The VM build script embeds the real 521-byte EEPROM block into a diagnostic binary named
`sample_dtof_official_offline_line_sweep_dbg`. The diagnostic tries:

- zero histogram input, to confirm the 2mm sentinel path;
- 8 simple `RAW12 + LINE` mask mappings:
  - normal bit order;
  - bit-reversed;
  - half-word swapped;
  - 64-bin inverted;
  - combinations of those three flags;
- 8 amplitudes per mapping: `512`, `1024`, `2048`, `4095`, `8191`, `16383`, `32767`,
  `65535`.

### 38.2 Build and deployment

EEPROM upload to VM:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text --allow-risk artifacts\dtof_eeprom_dtof_eeprom_j4_eeprom_official_20260602_150702_board_20260602_150704\gs1860_eeprom_521.bin /home/ebaina/gs1860_eeprom_521.bin
```

VM build command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "bash /home/ebaina/vm_build_official_offline_line_sweep.sh"
```

Result:

```text
BUILD_DIR=/home/ebaina/official_dtof_offline_line_sweep_20260602_151532
BINARY=/home/ebaina/official_dtof_offline_line_sweep_20260602_151532/src/dtof/sample_dtof_official_offline_line_sweep_dbg
binary_sha256=7ee45a52ecc252dfd6efe3f4663ff628800b297930f36a061b82d05412d242e6
binary_size=4529936
```

Deployment:

```powershell
.venv\Scripts\python tools\deploy_vm_binary_to_board_official.py --vm-binary /home/ebaina/official_dtof_offline_line_sweep_20260602_151532/src/dtof/sample_dtof_official_offline_line_sweep_dbg
```

Result:

```text
BOARD_UPLOAD_METHOD=ssh_base64_fallback
/opt/sample/official_dtof/sample_dtof_official_offline_line_sweep_dbg
board_binary_sha256=7ee45a52ecc252dfd6efe3f4663ff628800b297930f36a061b82d05412d242e6
mode=-rwxr-xr-x
```

### 38.3 Sweep run

Run command:

```powershell
.venv\Scripts\python tools\run_dtof_offline_line_sweep.py --condition f001_eeprom_mask_sweep --binary sample_dtof_official_offline_line_sweep_dbg --dump dtof_line_dump_f001.bin
```

Artifacts:

```text
logs/dtof_offline_line_sweep_f001_eeprom_mask_sweep_20260602_152202_commands.txt
logs/dtof_offline_line_sweep_f001_eeprom_mask_sweep_20260602_152202_board.log
logs/dtof_offline_line_sweep_f001_eeprom_mask_sweep_20260602_152202_report.json
```

Input:

```text
raw_len=110112
stride_guess=3552
eeprom_len=521
DtofInit success
```

Result summary after excluding invalid near values (`2mm` sentinel and `0mm`):

```text
variant_count=65
near_majority_count=0
zero_input: median=2, eq2=1200, near_valid_lt1000=0
best_nonzero_mask: mask_m1/mask_m6 amplitude=512
best_nonzero_mask_median=6000
best_nonzero_mask_center=6192
best_nonzero_mask_near_valid_lt1000=0
```

All nonzero mask variants remained far-depth dominated. Typical nonzero mask medians were
about `6.0m` to `7.0m`, with sparse `0mm`/`2mm` invalid pixels but no valid `<1m`
majority.

### 38.4 Conclusion

This rules out a broad class of simple software reconstructions:

- one-cleared-bit mask segment at byte offset `16`;
- bit-order reversal;
- half-word swapping;
- 64-bin inversion;
- simple amplitude scaling.

The saved `RAW12 + LINE` frame cannot be converted into a valid near-depth histogram for
`DtofProcess()` by those simple mask interpretations. The remaining likely roots are:

- the LINE payload has additional per-line payload/delta information not decoded by the
  mask-only reconstruction;
- the hardware/driver LINE decompression stage is required before `DtofProcess()`;
- the current saved dump is not the right post-decompression source for the library input;
- physical/trigger/light-path evidence still needs a fresh `clear / near / covered`
  comparison once the user confirms the required scene changes.

Safety status:

- No board sensor/VI/MIPI/UDP path was started by the offline sweep.
- No VM UDP listener was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.
- Read-only post-run check found no matching residual process.

## 39. 2026-06-02 offline unpack sweep with real EEPROM

This step extended the offline `DtofProcess()` evidence from mask-only guesses to explicit
RAW unpack interpretations of the saved `RAW12 + LINE` dump bytes. It still did not start
`dtof_init.sh`, sensors, VI/MIPI, UDP, or any actuator path.

### 39.1 Tooling added

New build script:

```text
tools/vm_build_official_offline_unpack_sweep.sh
```

It builds a board-side offline diagnostic:

```text
sample_dtof_official_offline_unpack_sweep_dbg
```

The diagnostic embeds the real 521-byte EEPROM block and tests these unpack families
against `DtofProcess()`:

- zero input, to confirm the `2mm` sentinel;
- `raw12_official_skip0`: same row-width assumption as official `deal_frame_data()`,
  decoding 2560 RAW12 pixels per measurement row even though compressed stride is only
  3552 bytes;
- `raw12_fit_skip0` and `raw12_fit_skip16`: RAW12 decoding constrained to the current
  row, with and without the 16-byte row prefix;
- `raw10_width_skip0` and `raw10_width_skip16`;
- `raw16le_width_skip0`, `raw16le_fit_skip0`, and `raw16le_fit_skip16`;
- `u8_fit_skip0` and `u8_fit_skip16`;
- gains `1`, `4`, `16`, and `64`.

### 39.2 Build and deployment

VM build command:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "bash /home/ebaina/vm_build_official_offline_unpack_sweep.sh"
```

Result:

```text
BUILD_DIR=/home/ebaina/official_dtof_offline_unpack_sweep_20260602_153040
BINARY=/home/ebaina/official_dtof_offline_unpack_sweep_20260602_153040/src/dtof/sample_dtof_official_offline_unpack_sweep_dbg
binary_sha256=ba734f9b64c8bca2e57017e119e71035677fb4797299204175f24440d7898139
binary_size=4534032
```

Deployment:

```powershell
.venv\Scripts\python tools\deploy_vm_binary_to_board_official.py --vm-binary /home/ebaina/official_dtof_offline_unpack_sweep_20260602_153040/src/dtof/sample_dtof_official_offline_unpack_sweep_dbg
```

Result:

```text
BOARD_UPLOAD_METHOD=ssh_base64_fallback
/opt/sample/official_dtof/sample_dtof_official_offline_unpack_sweep_dbg
board_binary_sha256=ba734f9b64c8bca2e57017e119e71035677fb4797299204175f24440d7898139
mode=-rwxr-xr-x
```

### 39.3 Runs

Frame 1:

```powershell
.venv\Scripts\python tools\run_dtof_offline_line_sweep.py --condition f001_eeprom_unpack_sweep --binary sample_dtof_official_offline_unpack_sweep_dbg --dump dtof_line_dump_f001.bin
```

Artifacts:

```text
logs/dtof_offline_line_sweep_f001_eeprom_unpack_sweep_20260602_153256_commands.txt
logs/dtof_offline_line_sweep_f001_eeprom_unpack_sweep_20260602_153256_board.log
logs/dtof_offline_line_sweep_f001_eeprom_unpack_sweep_20260602_153256_report.json
```

Frame 2:

```powershell
.venv\Scripts\python tools\run_dtof_offline_line_sweep.py --condition f002_eeprom_unpack_sweep --binary sample_dtof_official_offline_unpack_sweep_dbg --dump dtof_line_dump_f002.bin
```

Artifacts:

```text
logs/dtof_offline_line_sweep_f002_eeprom_unpack_sweep_20260602_153336_commands.txt
logs/dtof_offline_line_sweep_f002_eeprom_unpack_sweep_20260602_153336_board.log
logs/dtof_offline_line_sweep_f002_eeprom_unpack_sweep_20260602_153336_report.json
```

Both runs had:

```text
raw_len=110112
stride_guess=3552
eeprom_len=521
DtofInit success
variant_count=41
near_majority_count=0
```

Frame 1 best non-sentinel near count:

```text
raw10_width_skip0 gain=1 median=2 center=2 near_valid_lt1000=30 eq2=1169 zero=0
```

Frame 2 best non-sentinel near count:

```text
raw10_width_skip0 gain=1 median=2 center=2 near_valid_lt1000=30 eq2=1168 zero=2
```

The official RAW12-style interpretation remained dominated by the `2mm` sentinel:

```text
raw12_official_skip0 gain=1:
  f001 median=2 eq2=1199 center=2
  f002 median=2 eq2=1199 center=2
```

### 39.4 Conclusion

The unpack sweep confirms two important points:

- Replaying the official RAW12 unpack assumption on the saved `RAW12 + LINE` bytes mostly
  produces the same `2mm` sentinel behavior. This matches the field evidence that
  ordinary `deal_frame_data()` is not a valid LINE decompressor.
- RAW10, RAW16 little-endian, and direct u8 interpretations also fail to create a valid
  `<1m` majority. The small number of non-sentinel near pixels (`near_valid_lt1000=30`)
  is sparse and does not satisfy the acceptance gate.

Together with Section 38, this rules out:

- simple mask peak reconstruction;
- simple RAW10/RAW12/RAW16/u8 unpacking of the compressed LINE bytes;
- gain-only correction of those unpacked values.

The remaining software direction is to find or reproduce the actual vendor LINE
decompression/data contract before `DtofProcess()`. Without that, the next decisive
external evidence is still a fresh physical-condition comparison (`clear / near / covered`)
using saved LINE dumps, because the existing saved dumps are mostly mode-row identical and
do not establish scene responsiveness.

Safety status:

- No board sensor/VI/MIPI/UDP path was started by the unpack sweep.
- No VM UDP listener was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.
- Read-only post-run check found no matching residual process.

## 40. 2026-06-02 SDK and kernel symbol audit for LINE decompression path

This was a read-only audit to find a real vendor decompression path after Sections 38-39
ruled out simple user-space reconstruction of the saved `RAW12 + LINE` bytes.

Safety status for this audit:

- No board sample was started.
- No VM UDP listener was started.
- No sensor/VI/MIPI path was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.

### 40.1 Header and source search

Targeted SDK search:

```powershell
rg -n "compress_param|raw_frame_compress|decompress|send_pipe_raw|frame_source|OT_COMPRESS_MODE_LINE" vendor\SS928V100_SDK_V2.0.2.2_MPP_Sample-master\include vendor\SS928V100_SDK_V2.0.2.2_MPP_Sample-master\src -g "*.h" -g "*.c"
```

Relevant public interfaces found:

```text
ss_mpi_sys_set_raw_frame_compress_param()
ss_mpi_sys_get_raw_frame_compress_param()
ss_mpi_vi_get_pipe_compress_param()
ss_mpi_vi_set_pipe_frame_source()
ss_mpi_vi_get_pipe_frame_source()
ss_mpi_vi_send_pipe_raw()
```

No public user-space API was found that directly converts an `OT_COMPRESS_MODE_LINE`
raw frame buffer into an expanded raw/histogram buffer.

`ss_mpi_vi_send_pipe_raw()` is used in SDK samples as a VI user-frame replay path:

- set pipe source to `OT_VI_PIPE_FRAME_SOURCE_USER`;
- optionally run `ss_mpi_isp_run_once()`;
- send one or more raw frames using `ss_mpi_vi_send_pipe_raw()`;
- retrieve a VI/ISP output frame through the normal pipe/channel path.

This is not a standalone decompressor, but it is the only public path found that may route
a user-provided raw frame through the hardware VI/ISP processing path.

### 40.2 VM library symbol search

Read-only VM library search:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 180 run 'SDK=/home/ebaina/official_dtof_offline_unpack_sweep_20260602_153040; LIBDIR=$SDK/lib/linux/hisilicon; for lib in libss_mpi.a libss_isp.a libss_vgs.a libss_tde.a libss_mcf_vi.a; do p=$LIBDIR/$lib; [ -f $p ] || continue; echo ===$lib===; (aarch64-mix210-linux-nm -g --defined-only $p 2>/dev/null || nm -g --defined-only $p 2>/dev/null || true) | grep -Ei -e send_pipe_raw -e frame_source -e compress -e decompress -e raw_frame -e pipe_raw -e line | sed -n "1,80p"; done'
```

Relevant result:

```text
libss_mpi.a:
  ss_mpi_sys_get_raw_frame_compress_param
  ss_mpi_sys_set_raw_frame_compress_param
  ss_mpi_vi_get_pipe_compress_param
  ss_mpi_vi_get_pipe_frame_source
  ss_mpi_vi_send_pipe_raw
  ss_mpi_vi_set_pipe_frame_source
```

No exported `ss_mpi_*` or `ot_mpi_*` symbol matching a direct LINE decompressor was found
in the searched user-space libraries.

### 40.3 Board kernel module string search

Read-only board kernel module search:

```powershell
.venv\Scripts\python tools\board_run.py 'for f in /opt/ko/*.ko /ko/*.ko; do [ -f "$f" ] || continue; echo ===$f===; strings "$f" | grep -i -e decompress -e compress_param -e raw_frame -e line_compress -e set_cur_decompress -e send_pipe_raw | sed -n "1,40p"; done'
```

Relevant result:

```text
/opt/ko/ot_sys.ko:
  sys_set_raw_frame_compress
  sys_get_raw_frame_compress
  sys_drv_check_raw_frame_compress_param
  sys_drv_set_raw_frame_compress
  sys_drv_get_raw_frame_compress

/opt/ko/ot_tde.ko:
  tde_hal_node_set_src_to_decompress
  tde_osi_check_decompress_para

/opt/ko/ot_vi.ko:
  vi_get_pipe_compress_param
  vi_send_pipe_raw
  vi_check_send_pipe_raw_frame
  vi_hal_viproc_set_cur_decompress_param
  vi_hal_viproc_set_cur_decompress_en
  vi_hal_viproc_set_cur_decompress_cfg
  vi_hal_viproc_set_wdr_decompress_cfg
  vi_hal_viproc_set_wdr_decompress_param
  vi_hal_viproc_set_rref2_decompress_param
```

Interpretation:

- Kernel-side VI/VIPROC clearly has decompression controls.
- User-space exposes the pipe compression parameters and raw-frame replay path, but not a
  direct `decompress(raw_line_frame)` function.
- TDE still appears to be a 2D-surface decompression path and remains unsuitable as the
  primary RAW12/GS1860 histogram decompressor unless a specific RAW path is demonstrated.

### 40.4 Next software diagnostic candidate

The next software-only candidate, if proceeding without physical scene changes, is a
controlled VI user-source replay diagnostic:

```text
sample_dtof_official_vi_user_replay_dbg
```

Intended behavior:

1. Use the official dToF baseline and real EEPROM.
2. Allocate a VB/raw frame shaped like the saved `RAW12 + LINE` dump:
   `width=2560`, `height=31`, `stride=3552`, `pixel_format=RAW12`,
   `compress_mode=LINE`.
3. Load one saved `dtof_line_dump_fNNN.bin` into that frame.
4. Configure a VI pipe as `OT_VI_PIPE_FRAME_SOURCE_USER`.
5. Call `ss_mpi_isp_run_once()` if the selected pipe path requires it.
6. Send the raw frame with `ss_mpi_vi_send_pipe_raw()`.
7. Dump the resulting pipe/FE output frame and compare:
   - output frame `compress_mode`, `pixel_format`, `stride`, and nonzero structure;
   - whether the output can be passed to `DtofProcess()` without the 2mm sentinel.

This diagnostic would still be perception-only and actuator-free, but it would start and
modify the board media/VI runtime state. It must therefore be announced with exact
command, purpose, and risk before running.

If this replay path cannot be made to produce a decompressed/valid frame, the remaining
decisive evidence is a fresh physical-condition sequence (`clear / near / covered`) using
saved LINE dumps, because current saved dumps are mode-row identical and cannot prove
scene responsiveness.

## 41. 2026-06-02 VI user-source replay diagnostic results

This section executed the Section 40 replay candidate. The diagnostic remained
perception-only:

- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.
- No UDP listener or dToF UDP sender was started.
- The diagnostic initialized/exited MPP SYS/VB and temporarily created VI dev/pipe/chn
  state only for saved-frame replay.
- Read-only post-run process checks found no residual `sample_dtof`, RTSP, dToF listener,
  or UDP 2368 process.

### 41.1 Tools added

```text
tools/vm_build_official_vi_user_replay.sh
tools/run_dtof_vi_user_replay.py
```

The build script patches only a VM temporary copy of the official dToF baseline. It embeds
the real 521-byte GS1860 EEPROM calibration block and builds variants of:

- VI dev binding enabled/disabled;
- pipe bypass mode (`BE`, `FE`);
- pipe compression mode (`LINE`, `NONE`);
- input frame compression metadata (`LINE`, `NONE`);
- VI chn0 enabled/disabled.

### 41.2 Default J4 replay attempt

Built binary:

```text
/opt/sample/official_dtof/sample_dtof_official_vi_user_replay_dbg
sha256=e9729ef8485b26061441d7ac69a9d4d6c4433f8ce1b4221ebe88f2a7298dbedc
```

Run:

```powershell
.venv\Scripts\python tools\run_dtof_vi_user_replay.py --condition f001_vi_user_replay_dev3_pipe1 --binary sample_dtof_official_vi_user_replay_dbg --dump dtof_line_dump_f001.bin --pipe 1 --dev 3
```

Artifacts:

```text
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_pipe1_20260602_161948_commands.txt
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_pipe1_20260602_161948_board.log
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_pipe1_20260602_161948_report.json
```

Result:

```text
dev3 set_attr/enable/bind: success
pipe1 create/start BE + RAW12 + LINE: success
set pipe source USER: success
DtofInit with real EEPROM: success
ss_mpi_vi_send_pipe_raw(): 0xa010800d on pipe/fe_out/bas attempts
```

Decode:

```text
0xa010800d = VI / error level / OT_ERR_NOT_PERM
```

### 41.3 Attribute variants

Variant A, virtual pipe style without dev binding:

```text
binary=sample_dtof_official_vi_user_replay_fe_none_in_line_dbg
sha256=353afec9dbacac44742aef696695611b7bfd25b39d150376d827cd23eb825626
condition=f001_vi_user_replay_fe_none_in_line
pipe_bypass=FE
pipe_compress=NONE
input_compress=LINE
use_dev_bind=0
```

Artifacts:

```text
logs/dtof_vi_user_replay_f001_vi_user_replay_fe_none_in_line_20260602_162611_commands.txt
logs/dtof_vi_user_replay_f001_vi_user_replay_fe_none_in_line_20260602_162611_board.log
logs/dtof_vi_user_replay_f001_vi_user_replay_fe_none_in_line_20260602_162611_report.json
```

Result:

```text
ss_mpi_vi_create_pipe(): 0xa0108024
0xa0108024 = VI / error level / OT_ERR_NOT_BINDED
```

Variant B, dev3 binding with FE/NONE pipe:

```text
binary=sample_dtof_official_vi_user_replay_dev3_fe_none_in_line_dbg
sha256=b4e23d8baa078a4a6ad10d25056fe848b3f04e2dfb4d9b4fe3f61bfa06e9a668
condition=f001_vi_user_replay_dev3_fe_none_in_line
pipe_bypass=FE
pipe_compress=NONE
input_compress=LINE
use_dev_bind=1
```

Artifacts:

```text
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_fe_none_in_line_20260602_162904_commands.txt
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_fe_none_in_line_20260602_162904_board.log
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_fe_none_in_line_20260602_162904_report.json
```

Result:

```text
ss_mpi_vi_create_pipe(): 0xa0108007
0xa0108007 = VI / error level / OT_ERR_ILLEGAL_PARAM
```

Variant C, dev3 binding with BE/LINE pipe but uncompressed input metadata:

```text
binary=sample_dtof_official_vi_user_replay_dev3_be_line_in_none_dbg
sha256=d96d44b84a8a76a8dbda331687010d7f1b3de99b057dd7066f372e626c6b4d51
condition=f001_vi_user_replay_dev3_be_line_in_none
pipe_bypass=BE
pipe_compress=LINE
input_compress=NONE
use_dev_bind=1
```

Artifacts:

```text
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_in_none_20260602_163137_commands.txt
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_in_none_20260602_163137_board.log
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_in_none_20260602_163137_report.json
```

Result:

```text
pipe create/start: success
ss_mpi_vi_send_pipe_raw(): 0xa010800d
```

Variant D, closest to official dToF pipe state, with chn0 enabled:

```text
binary=sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg
sha256=b2786dfc14b858ee3cb3536de6e16c6113d68d1664e2c2d4e7375e93c951bac7
condition=f001_vi_user_replay_dev3_be_line_chn
pipe_bypass=BE
pipe_compress=LINE
input_compress=LINE
use_dev_bind=1
chn0=enabled
```

Artifacts:

```text
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_chn_20260602_163510_commands.txt
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_chn_20260602_163510_board.log
logs/dtof_vi_user_replay_f001_vi_user_replay_dev3_be_line_chn_20260602_163510_report.json
```

Result:

```text
dev3 set_attr/enable/bind: success
pipe1 create/start BE + RAW12 + LINE: success
chn0 set_attr/enable: success
set dump attrs and USER source: success
ss_mpi_vi_send_pipe_raw(): 0xa010800d
```

### 41.4 Conclusion

The public `ss_mpi_vi_send_pipe_raw()` replay path does not currently provide a practical
user-space LINE decompression route for the saved GS1860 `RAW12 + LINE` frames.

Evidence:

- A physical dev3->pipe1 binding is required for BE/LINE pipe creation.
- FE/NONE with no active dev is not accepted as a standalone virtual pipe on this board
  state (`OT_ERR_NOT_BINDED`).
- FE/NONE with dev3 binding is an illegal pipe-attribute combination.
- The closest official dToF pipe state (`dev3`, `pipe1`, `BE`, `RAW12`, `LINE`, chn0
  enabled, source USER) still rejects `ss_mpi_vi_send_pipe_raw()` with `OT_ERR_NOT_PERM`.
- Marking the input frame as uncompressed `NONE` does not change the `OT_ERR_NOT_PERM`
  result on BE/LINE.

Therefore, the remaining high-value path is no longer replaying old LINE dumps through
public VI user-source APIs. The next decisive step is fresh physical-condition capture:

1. clear scene;
2. near obstruction within 30 cm;
3. covered/blocked dToF aperture if needed.

The goal is to determine whether the live GS1860 raw LINE frame changes with the scene. If
the live raw bytes change but `DtofProcess()` still produces 2 mm or approximately 5 m,
continue with vendor data-contract/config investigation. If the raw bytes do not change
with physical scene changes, prioritize physical optical path, port, cable, power, J3/J4,
and MIPI mapping.

## 42. 2026-06-02 physical-condition capture preflight

After Section 41 ruled out public VI user-source replay as a practical decompression
shortcut, the next decisive evidence requires live captures under known physical scene
conditions.

Read-only preflight checks:

```powershell
.venv\Scripts\python tools\board_run.py "hostname; date; ps w | grep -E 'sample_dtof|rtsp|dtof|listen|2368|mcu|can|actuator|serial' | grep -v grep || true; cd /opt/sample/official_dtof 2>/dev/null && sha256sum sample_dtof_official_j4cfg_dbg sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg sample_dtof_official_line_dump_cp_dbg 2>/dev/null; ls -l /opt/sample/official_dtof 2>/dev/null | sed -n '1,80p'"
```

Board result summary:

```text
hostname=(none)
date=Tue Jun  2 12:48:35 UTC 2026
ps output contained only sshd and wpa_supplicant from the broad grep
no sample_dtof / rtsp / dtof / UDP 2368 / actuator / MCU process found
wpa_supplicant is a false-positive from the broad "can" substring search, not CAN actuator software
sample_dtof_official_j4cfg_dbg sha256=a6398c9cb6c36c3bf36b97ea8c0d8bc00fbfd3c3c8467a307d18f06353a7b56c
sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg sha256=b2786dfc14b858ee3cb3536de6e16c6113d68d1664e2c2d4e7375e93c951bac7
sample_dtof_official_line_dump_cp_dbg sha256=3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea
```

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 60 run "hostname; date; (ss -lunp 2>/dev/null || netstat -lunp 2>/dev/null || true) | grep ':2368' || true; ps aux | grep -E 'sample_dtof|dtof|2368|foxglove|ros|rtsp' | grep -v grep || true"
```

VM result summary:

```text
hostname=ebaina-virtual-machine
date=2026-06-02 16:39:21 CST
UDP 2368 not occupied
existing Foxglove bridge process is running on port 8765
```

Existing capture tooling:

```text
tools/capture_dtof_line_condition.py
tools/compare_dtof_line_conditions.py
```

`capture_dtof_line_condition.py` is suitable for the next physical-condition step:

- records the board's existing `dtof_line_dump_f*.bin/.meta` state before capture;
- runs the perception-only line-dump sample through `run_dtof_phase1_condition.py`;
- downloads only new or changed dump files into `artifacts/`;
- runs single-condition line-dump analysis and mask-hypothesis analysis.

Next user-gated physical sequence:

1. User clears the dToF field of view and replies `clear_done`.
2. Run:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear_j4_live --binary sample_dtof_official_line_dump_cp_dbg --case 2 --seconds 8 --max-packets 20
```

3. User places an obstruction within 30 cm and replies `near30_done`.
4. Run:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition near30_j4_live --binary sample_dtof_official_line_dump_cp_dbg --case 2 --seconds 8 --max-packets 20
```

5. Compare the resulting artifact directories with:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py clear=<clear_artifact_dir> near30=<near30_artifact_dir>
```

Safety note:

- These capture commands start only the board dToF sample and VM UDP checker.
- They do not start MCU bridge, CAN actuator, serial actuator, motor, steering, brake,
  throttle, or chassis-control software.
- They still change board/VM perception runtime state, so the exact command, purpose, and
  risk must be shown before running.

## 43. 2026-06-02 existing board LINE dump download and analysis-tool validation

This was a read-only validation of the local analysis chain using the existing saved board
dump files. No live sample was started.

Command:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition existing_board_line_dumps_20260602 --skip-run
```

Safety status:

- `--skip-run` was used, so no board dToF sample was started.
- No VM UDP listener was started.
- No sensor/VI/MIPI runtime state was changed.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control process was started.

Tooling fix made during this validation:

- `tools/capture_dtof_line_condition.py` now keeps the SFTP path but falls back to SSH
  `base64` download when the board SFTP subsystem returns `EOF during negotiation`.
- This matches the board behavior seen during binary deployment and prevents future
  physical-condition captures from failing at the artifact download step.

Observed fallback:

```text
SFTP_DOWNLOAD_FALLBACK=ssh_base64 reason=SSHException: EOF during negotiation
```

Artifacts:

```text
artifacts/dtof_line_dump_existing_board_line_dumps_20260602_20260602_164648/
  capture_manifest.txt
  dtof_line_dump_f001.bin/.meta
  dtof_line_dump_f002.bin/.meta
  dtof_line_dump_f003.bin/.meta
  dtof_line_dump_f004.bin/.meta
  line_dump_analysis.json
  line_mask_hypothesis_analysis.json
```

Downloaded files:

```text
DOWNLOADED_FILES=8
```

Single-condition summary:

```text
frame_count=4
file_size=110112 for each frame
width=2560
height=31
stride0=3552
pixel_format=21
compress_mode=4
compress_param_sha256=647057ba5f7082a05286f32fd737c0c005586a032bbe3f84e8427213b95e0c9a
row1_nonzero=342 for all four frames
row1_first64 identical across all four frames
```

Frame SHA prefixes:

```text
f001 fa5ede25d845d9df
f002 1c937c13e16986b1
f003 f2744b52f387d723
f004 baac972ff1df85bb
```

Mask-structure summary:

```text
frame_count=4
expected_mask_words=80
best_start_word=4 for all four frames
mask_words_match_40x64=true
top active bins include 11,44,13,46,15,48,17,50...
```

Interpretation:

- The analysis chain works on current board artifacts and can be used for the next
  clear/near/covered captures.
- The existing board dumps reproduce the previous structural finding: the saved LINE data
  has a stable 80-word `40 columns * 64 bins` mask-like region, but this does not recover
  amplitudes and does not prove `DtofProcess()` can consume it.
- The existing dumps are not enough to prove scene responsiveness because they were not
  captured under freshly controlled physical conditions. The next decisive evidence is
  still fresh `clear` then `near30cm` capture.

## 44. 2026-06-02 capture wrapper quiet-analysis validation

After Section 43, `tools/capture_dtof_line_condition.py` was further improved so future
live physical-condition captures remain readable:

- `analyze_dtof_line_dump.py` stdout is written to `line_dump_analysis.stdout.log`.
- `analyze_dtof_line_mask_hypothesis.py` stdout is written to
  `line_mask_hypothesis_analysis.stdout.log`.
- The wrapper still writes full JSON reports, but only prints a compact summary to the
  terminal.

This is important for the upcoming `clear` and `near30cm` live captures because the
analysis JSON can be thousands of lines long.

Validation command, still read-only:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition existing_board_line_dumps_quiet_20260602 --skip-run
```

Safety status:

- `--skip-run` was used.
- No board dToF sample was started.
- No VM UDP listener was started.
- No sensor/VI/MIPI runtime state was changed.
- No actuator or chassis-control process was started.

Artifacts:

```text
artifacts/dtof_line_dump_existing_board_line_dumps_quiet_20260602_20260602_165417/
  capture_manifest.txt
  dtof_line_dump_f001.bin/.meta
  dtof_line_dump_f002.bin/.meta
  dtof_line_dump_f003.bin/.meta
  dtof_line_dump_f004.bin/.meta
  line_dump_analysis.json
  line_dump_analysis.stdout.log
  line_mask_hypothesis_analysis.json
  line_mask_hypothesis_analysis.stdout.log
```

Observed terminal summary:

```text
SFTP_DOWNLOAD_FALLBACK=ssh_base64 reason=SSHException: EOF during negotiation
DOWNLOADED_FILES=8
LINE_FRAME_COUNT=4
LINE_FRAME frame=1 sha16=fa5ede25d845d9df width=2560 height=31 stride0=3552 pixfmt=21 compress=4 row1_nonzero=342
LINE_FRAME frame=2 sha16=1c937c13e16986b1 width=2560 height=31 stride0=3552 pixfmt=21 compress=4 row1_nonzero=342
LINE_FRAME frame=3 sha16=f2744b52f387d723 width=2560 height=31 stride0=3552 pixfmt=21 compress=4 row1_nonzero=342
LINE_FRAME frame=4 sha16=baac972ff1df85bb width=2560 height=31 stride0=3552 pixfmt=21 compress=4 row1_nonzero=342
MASK_FRAME_COUNT=4
MASK_BEST_START_WORD_COUNTS=[[4, 4]]
MASK_MATCH_40X64=True
```

Tooling conclusion:

- The fallback download path works.
- The analysis path works.
- The wrapper is ready for the next live `clear_j4_live` capture once the user confirms
  the physical dToF field of view is clear.

## 45. 2026-06-02 LINE condition compare compact-summary validation

`tools/compare_dtof_line_conditions.py` was improved for the upcoming physical-condition
comparison:

- `--summary` prints a compact terminal report instead of the full JSON report.
- `--summary-out <path>` writes that compact report to a separate file.
- `--out <path>` still writes the full JSON report for later forensic analysis.
- Existing default behavior is preserved when `--summary` is not used.

Validation used only existing local artifacts:

```powershell
.venv\Scripts\python tools\compare_dtof_line_conditions.py existing=artifacts\dtof_line_dump_existing_board_line_dumps_20260602_20260602_164648 quiet=artifacts\dtof_line_dump_existing_board_line_dumps_quiet_20260602_20260602_165417 --out logs\tmp_existing_vs_quiet_compare_quiet.json --summary --summary-out logs\tmp_existing_vs_quiet_compare_quiet_summary.txt
```

Safety status:

- Local read-only artifact comparison only.
- No board dToF sample was started.
- No VM UDP listener was started.
- No board or VM runtime state was changed.
- No actuator or chassis-control process was started.

Artifacts:

```text
logs/tmp_existing_vs_quiet_compare_quiet.json
logs/tmp_existing_vs_quiet_compare_quiet_summary.txt
```

Observed compact summary:

```text
DTOF_LINE_CONDITION_COMPARE_SUMMARY
CONDITION label=existing frames=4 measurement_rows=120 width=2560 height=31 stride0=3552 pixfmt=21 compress=4 compress_param_sha16=647057ba5f7082a0
  mask_best_start=[[4,120]] active_bins_top=[[11,240],[44,240],[13,240],[46,240],[15,240],[48,240],[17,240],[50,240],[19,240],[52,240]] row_hash_top=[["ffee246e133657fa",117],["6b5a6556669c37ee",1],["dcd1ae73bb584d4e",1],["b1df3d4c56dc3682",1]]
CONDITION label=quiet frames=4 measurement_rows=120 width=2560 height=31 stride0=3552 pixfmt=21 compress=4 compress_param_sha16=647057ba5f7082a0
  mask_best_start=[[4,120]] active_bins_top=[[11,240],[44,240],[13,240],[46,240],[15,240],[48,240],[17,240],[50,240],[19,240],[52,240]] row_hash_top=[["ffee246e133657fa",117],["6b5a6556669c37ee",1],["dcd1ae73bb584d4e",1],["b1df3d4c56dc3682",1]]
PAIR left=existing right=quiet changed_byte_offsets=0 changed_word_offsets=0 mask_delta_count=0 zero_changed_byte_offsets=True
  top_byte_offsets=[] top_word_offsets=[] top_mask_bin_deltas=[]
```

Interpretation:

- The comparison logic correctly reports zero differences for two artifact directories
  derived from the same historical board dumps.
- This is a tooling validation only; it does not prove scene responsiveness.
- The next decisive evidence remains fresh live `clear` then `near30cm` LINE captures
  after the user confirms the physical dToF field of view is clear.

## 46. 2026-06-02 pre-live readonly safety/status check

Before any fresh live physical-condition capture, the workspace, board, and VM were
rechecked with read-only commands.

Safety status:

- No board dToF sample was started.
- No VM UDP listener was started.
- No board or VM runtime state was changed.
- No actuator or chassis-control process was started.
- The broad process filters only read `ps`/socket state. A process named
  `wpa_supplicant` matches the substring `can` but is not a CAN actuator process.

Board basic check:

```powershell
.venv\Scripts\python tools\board_run.py 'echo BOARD_BASIC; date; whoami; uname -a'
```

Observed:

```text
BOARD_BASIC
Tue Jun  2 13:18:33 UTC 2026
root
Linux (none) 4.19.90 #1 SMP Fri Jan 30 11:45:17 CST 2026 aarch64 GNU/Linux
```

Board process check:

```powershell
.venv\Scripts\python tools\board_run.py 'echo BOARD_PROCESS_CHECK_CLEAN; ps -ef | grep -e sample_dtof -e rtsp -e dtof -e mcu -e actuator -e motor -e steer -e brake -e throttle -e can -e serial | grep -v grep || true'
```

Observed:

```text
BOARD_PROCESS_CHECK_CLEAN
 1867 root      0:09 wpa_supplicant -iwlan0 -Dnl80211 -c/etc/wireless/wpa_supplicant.conf
```

Interpretation: no `sample_dtof`, RTSP, dToF runtime, MCU bridge, CAN actuator, serial
actuator, motor, steering, brake, or throttle process was observed. The only hit is the
expected wireless supplicant false positive caused by the substring `can`.

Board deployed binary/config hashes from `/opt/sample/official_dtof`:

```text
a6398c9cb6c36c3bf36b97ea8c0d8bc00fbfd3c3c8467a307d18f06353a7b56c  sample_dtof_official_j4cfg_dbg
3105f0b53e122a123066d25a68517bfc2b82db9447e7a84adf1580da5ff3d0ea  sample_dtof_official_line_dump_cp_dbg
b2786dfc14b858ee3cb3536de6e16c6113d68d1664e2c2d4e7375e93c951bac7  sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg
eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0  dtof_init.sh
7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6  dtof.ini
3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb  gs1860_register.ini
```

Board media/port check:

```powershell
.venv\Scripts\python tools\board_run.py 'echo BOARD_MEDIA_AND_PORTS_CLEAN; echo MODULES; cat /proc/modules | grep -i -e mipi -e vi -e isp -e vpss -e sensor -e os08 -e gs1860 -e ot_ -e ss_ || true; echo UDP_2368; ss -lunp 2>/dev/null | grep 2368 || true; netstat -lunp 2>/dev/null | grep 2368 || true'
```

Observed media stack includes `ot_mipi_rx`, `ot_isp`, `ot_vi`, and `ot_vpss`.
`UDP_2368` produced no listener line on the board.

VM process/port check:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run 'echo VM_PROCESS_AND_PORTS_CLEAN; ps -ef | grep -e sample_dtof -e rtsp -e dtof -e mcu -e actuator -e motor -e steer -e brake -e throttle -e can -e serial -e foxglove_bridge -e ros2 | grep -v grep || true; echo UDP_2368; ss -lunp | grep 2368 || true; echo TCP_8765; ss -ltnp | grep 8765 || true'
```

Observed:

- No VM dToF UDP receiver is bound to UDP `2368`.
- Existing Foxglove bridge remains on TCP `8765`.
- No MCU/actuator/motor/steering/brake/throttle process was observed.
- VM tool log: `logs/vm_ssh_20260602_171033_cd0f5b42.log`.

Official build sensor macro evidence:

```powershell
rg -n "SENSOR0_TYPE|SENSOR2_TYPE" tools\vm_build_official_dtof_clean.sh tools\vm_build_official_line_dump.sh tools\vm_build_official_vi_user_replay.sh
```

Observed:

```text
tools\vm_build_official_line_dump.sh:155:  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
tools\vm_build_official_line_dump.sh:157:  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
tools\vm_build_official_dtof_clean.sh:46:  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
tools\vm_build_official_dtof_clean.sh:48:  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
tools\vm_build_official_vi_user_replay.sh:890:  SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
tools\vm_build_official_vi_user_replay.sh:892:  SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
```

Conclusion:

- The board and VM are reachable.
- The official deployed board directory exists and contains the expected debug binaries,
  scripts, and dToF config files.
- UDP `2368` is free for the next dToF capture.
- The next live step remains blocked on physical scene confirmation: user clears the
  dToF field of view and replies `clear_done`.

## 47. 2026-06-02 live dToF preflight gate tool

A dedicated read-only preflight tool was added:

```text
tools/dtof_live_preflight.py
```

Purpose:

- Run fixed read-only board and VM checks before live dToF perception captures.
- Verify no known dToF sample or actuator-like process is already running.
- Verify UDP `2368` is free on the board and VM.
- Verify deployed official dToF binaries/config files match the expected SHA-256 values.
- Save both full JSON evidence and a compact summary under `logs/`.

Safety status:

- The tool only runs fixed read-only commands.
- It does not start a board dToF sample.
- It does not start a VM UDP listener.
- It does not change board or VM runtime state.
- It does not start any actuator or chassis-control process.

Validation commands:

```powershell
.venv\Scripts\python -m py_compile tools\dtof_live_preflight.py

.venv\Scripts\python tools\dtof_live_preflight.py --out logs\dtof_live_preflight_20260602_manual.json --summary-out logs\dtof_live_preflight_20260602_manual_summary.txt
```

Artifacts:

```text
logs/dtof_live_preflight_20260602_manual.json
logs/dtof_live_preflight_20260602_manual_summary.txt
```

Observed compact summary:

```text
DTOF_LIVE_PREFLIGHT_SUMMARY
timestamp=2026-06-02T17:19:10
pass=True
issues=[]
warnings=["VM TCP 8765 is occupied, usually by the existing Foxglove bridge"]
board_unsafe_process_count=0
vm_unsafe_process_count=0
board_udp_2368_occupied=False
vm_udp_2368_occupied=False
vm_tcp_8765_lines=1
board_hash_ok=sample_dtof_official_j4cfg_dbg,sample_dtof_official_line_dump_cp_dbg,sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg,dtof_init.sh,dtof.ini,gs1860_register.ini
board_hash_bad=
board_process_lines=[" 1867 root      0:09 wpa_supplicant -iwlan0 -Dnl80211 -c/etc/wireless/wpa_supplicant.conf"]
vm_tcp_8765=["LISTEN 0      1024         0.0.0.0:8765       0.0.0.0:*    users:((\"foxglove_bridge\",pid=47704,fd=25))"]
```

Interpretation:

- The preflight gate passes.
- The `wpa_supplicant` board line is the same harmless `can` substring false positive.
- The existing Foxglove bridge on VM TCP `8765` is expected and does not occupy UDP `2368`.
- This preflight should be run immediately before the next live `clear_j4_live` and
  `near30cm` captures.

## 48. 2026-06-02 Phase1 live wrapper preflight integration

`tools/run_dtof_phase1_condition.py` was updated so live Phase1 dToF captures run the
read-only preflight gate before starting any VM UDP receiver or board `sample_dtof`
process.

Behavior:

- By default, the wrapper runs `tools/dtof_live_preflight.py` first.
- If preflight fails, the wrapper exits immediately and does not start VM UDP capture or
  board dToF sample.
- `--preflight-only` runs the preflight and exits before live capture. This is for safe
  integration verification.
- `--skip-preflight` exists only as an explicit escape hatch; it is not part of the
  normal bring-up route.
- The command log now records the preflight command, planned VM command, planned board
  command, and whether the mode is live capture or preflight-only.

Validation commands:

```powershell
.venv\Scripts\python -m py_compile tools\run_dtof_phase1_condition.py tools\dtof_live_preflight.py

.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition preflight_only_j4_live_gate_v2 --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20 --preflight-only
```

Safety status:

- `--preflight-only` was used.
- No VM UDP listener was started.
- No board dToF sample was started.
- No actuator or chassis-control process was started.

Artifacts:

```text
logs/dtof_phase1_preflight_only_j4_live_gate_v2_20260602_172450_commands.txt
logs/dtof_phase1_preflight_only_j4_live_gate_v2_20260602_172450_preflight.json
logs/dtof_phase1_preflight_only_j4_live_gate_v2_20260602_172450_preflight_summary.txt
logs/dtof_phase1_preflight_only_j4_live_gate_v2_20260602_172450_preflight_stdout.log
```

Observed terminal end:

```text
PREFLIGHT_RC=0
PREFLIGHT_ONLY=1
Not starting VM UDP capture or board dToF sample.
```

Command-log mode line:

```text
Mode:
preflight-only; VM and board live capture commands will not be executed.
```

Observed preflight summary:

```text
DTOF_LIVE_PREFLIGHT_SUMMARY
timestamp=2026-06-02T17:24:54
pass=True
issues=[]
warnings=["VM TCP 8765 is occupied, usually by the existing Foxglove bridge"]
board_unsafe_process_count=0
vm_unsafe_process_count=0
board_udp_2368_occupied=False
vm_udp_2368_occupied=False
vm_tcp_8765_lines=1
board_hash_ok=sample_dtof_official_j4cfg_dbg,sample_dtof_official_line_dump_cp_dbg,sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg,dtof_init.sh,dtof.ini,gs1860_register.ini
board_hash_bad=
```

Conclusion:

- The live wrapper now has an enforced read-only safety/status gate by default.
- The gate passes in the current board/VM state.
- The next live step is still waiting for physical scene confirmation: user clears the
  dToF field of view and replies `clear_done`.

## 49. 2026-06-02 latest LINE artifact compare/decision helper

A post-capture helper was added:

```text
tools/dtof_line_latest_compare.py
```

Purpose:

- Find the latest `artifacts/dtof_line_dump_<label>_*` directories for two conditions,
  or accept explicit `label=path` artifact directories.
- Run `tools/compare_dtof_line_conditions.py` with compact summary output.
- Write a decision JSON and decision summary focused on whether saved RAW12+LINE data
  changed between the two physical conditions.

Scope:

- This helper only evaluates whether raw LINE artifacts differ between conditions.
- It does not prove `DtofProcess()` distance correctness.
- It is intended to route the next diagnosis after fresh `clear` and `near30cm` captures:
  if raw LINE changes but output/UDP stays at `2mm` or about `5m`, inspect the vendor
  decode/data contract; if raw LINE does not change, prioritize physical light path,
  J3/J4 mapping, trigger/config, power, or MIPI routing.

Default future use after live captures:

```powershell
.venv\Scripts\python tools\dtof_line_latest_compare.py clear_j4_live near30cm_j4_live
```

Validation used a negative control: two artifact directories derived from the same
historical board dumps.

```powershell
.venv\Scripts\python -m py_compile tools\dtof_line_latest_compare.py tools\compare_dtof_line_conditions.py

.venv\Scripts\python tools\dtof_line_latest_compare.py existing=artifacts\dtof_line_dump_existing_board_line_dumps_20260602_20260602_164648 quiet=artifacts\dtof_line_dump_existing_board_line_dumps_quiet_20260602_20260602_165417 --out logs\dtof_line_compare_existing_vs_quiet_latest_tool.json --summary-out logs\dtof_line_compare_existing_vs_quiet_latest_tool_summary.txt --decision-out logs\dtof_line_compare_existing_vs_quiet_latest_tool_decision.json --decision-summary-out logs\dtof_line_compare_existing_vs_quiet_latest_tool_decision_summary.txt
```

Safety status:

- Local artifact comparison only.
- No board dToF sample was started.
- No VM UDP listener was started.
- No actuator or chassis-control process was started.

Artifacts:

```text
logs/dtof_line_compare_existing_vs_quiet_latest_tool.json
logs/dtof_line_compare_existing_vs_quiet_latest_tool_summary.txt
logs/dtof_line_compare_existing_vs_quiet_latest_tool_decision.json
logs/dtof_line_compare_existing_vs_quiet_latest_tool_decision_summary.txt
```

Observed decision summary:

```text
DTOF_LINE_LATEST_COMPARE_DECISION
left=existing path=artifacts\dtof_line_dump_existing_board_line_dumps_20260602_20260602_164648
right=quiet path=artifacts\dtof_line_dump_existing_board_line_dumps_quiet_20260602_20260602_165417
decision=NO_LINE_SCENE_CHANGE_OBSERVED
raw_line_scene_change=no
changed_byte_offsets=0
changed_word_offsets=0
mask_delta_count=0
recommended_next=If these were controlled clear/near captures, prioritize physical light path, J3/J4 mapping, trigger/config, power, or MIPI routing before ROS thresholds.
```

Conclusion:

- The helper correctly does not report scene-dependent raw LINE change for same-source
  historical artifacts.
- It is ready to run after fresh live `clear_j4_live` and `near30cm` artifacts exist.

## 50. 2026-06-02 official dToF config drift/static mode audit

Before the next physical-condition capture, the currently deployed board config files were
audited against the official vendor baseline.

Safety status:

- Read-only board `sha256sum`/`sed` commands only.
- Read-only local vendor file inspection only.
- No board dToF sample was started.
- No VM UDP listener was started.
- No actuator or chassis-control process was started.

Board config hashes:

```text
7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6  /opt/sample/official_dtof/dtof.ini
3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb  /opt/sample/official_dtof/gs1860_register.ini
```

Vendor baseline hashes:

```text
7BBF91218B669893394F90D51C6435858101FAB63CD5D4D82FD688732AABDEB6  vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/dtof.ini
3546A82D5E58BDA430C69C2FF3A40DD0E73BF5FA65F697CBE0A902D4B35708BB  vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof/gs1860_register.ini
```

Conclusion: the deployed board `dtof.ini` and `gs1860_register.ini` are byte-identical
to the official vendor baseline.

Key `dtof.ini` parameters:

```text
spadWidth=40
spadHeight=30
binNum=64
validBinNum=62
thresholdProb=0.002
configSwitchFlag=false
tdcTimeBinNear=500
tdcTimeBinFar=1000
totalShotNumNear=30000
totalShotNumFar=30000
distThreshold=2000.0
temperatureBypass=false
logEvent=0
```

Key `gs1860_register.ini` sections:

```text
[1000ps]
0x1318=0x00007530
0x1064=0x08200CE8
0x1068=0x11F81B34

[500ps]
0x1318=0x00007530
0x1064=0x082000E0
0x1068=0x39B01B54

[pwm1000ps]
0x62=0x04E2
0x82=0x0005

[pwm500ps]
0x62=0x0589
0x82=0x0005

[i2cAddr]
0x744=0x28
0x4550=0x50
```

Static source findings:

- `sample_dtof.c` loads `./gs1860_register.ini` through `gs1860_read_ini_file(...)`.
- `sample_dtof.c` does not directly call `gs1860_500ps_config(...)` or
  `gs1860_1000ps_config(...)`.
- `dtof_dumpraw.c` can switch dynamically after `DtofProcess()` sets
  `handle->dtofOutput.switchFlag`.
- `dtof_dumpraw.c` has a `DTOF_FORCE_500PS_CONFIG` hook, but the current
  `tools/vm_build_official_line_dump.sh` command line does not define that macro:

```text
EXTRA_CFLAGS="-DDTOF_KEEP_PIPE_ATTR -DDTOF_DUMP_SOURCE=${DUMP_SOURCE} -DDTOF_LINE_DUMP_FRAMES=${LINE_DUMP_FRAMES}"
```

Interpretation:

- Config drift is not the current explanation for the bad near-distance behavior.
- The official config contains both 500ps and 1000ps register groups, but automatic
  near/far mode switching is disabled in `dtof.ini` (`configSwitchFlag=false`).
- The next decisive evidence is still live physical-condition data. If raw LINE changes
  with a near target but DtofProcess/UDP remains at `2mm` or about `5m`, mode selection
  and the DtofProcess data contract should stay high-priority suspects. If raw LINE does
  not change, prioritize physical light path, J3/J4 mapping, trigger/config, power, or
  MIPI routing.

## 51. 2026-06-02 board_run UTF-8 output hardening

While auditing `gs1860_register.ini`, `tools/board_run.py` hit a Windows console
`UnicodeEncodeError` when printing board-side config comments containing non-ASCII bytes.
The command itself was read-only and the board config hash had already been obtained, but
the local wrapper output path was fragile.

`tools/board_run.py` was updated to:

- force `stdout` and `stderr` to UTF-8 with replacement,
- keep the existing call form `.venv\Scripts\python tools\board_run.py "<cmd>"`,
- add a local `--help`/empty-command usage path that does not connect to the board,
- close the SSH client in a `finally` block.

Validation commands:

```powershell
.venv\Scripts\python -m py_compile tools\board_run.py

.venv\Scripts\python tools\board_run.py --help

.venv\Scripts\python tools\board_run.py 'cd /opt/sample/official_dtof && echo BOARD_GS1860_REGISTER_SHA && sha256sum gs1860_register.ini && echo BOARD_GS1860_REGISTER_SAMPLE && sed -n "109,124p" gs1860_register.ini'
```

Safety status:

- Local Python syntax/help checks only.
- Board command was read-only `sha256sum`/`sed`.
- No board dToF sample was started.
- No VM UDP listener was started.
- No actuator or chassis-control process was started.

Observed board read output now completes successfully:

```text
BOARD_GS1860_REGISTER_SHA
3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb  gs1860_register.ini
BOARD_GS1860_REGISTER_SAMPLE
[pwmCommon]
...
[pwm1000ps]
0x62=0x04E2
0x82=0x0005

[pwm500ps]
0x62=0x0589
0x82=0x0005

[i2cAddr]
0x744=0x28
0x4550=0x50
```

Conclusion:

- `tools/board_run.py` can now safely print lossy UTF-8 board output on the Windows host
  without failing the command.
- This improves reliability for future board-side log/config collection before and after
  live dToF captures.

## 52. 2026-06-02 board_run risk gate hardening

`tools/board_run.py` was further hardened to reduce the chance of accidentally sending
dangerous board commands during perception bring-up.

New behavior:

- Supports `--allow-risk` for explicitly approved important/dangerous board commands.
- Refuses risk-pattern commands by default, including package install, `systemctl`,
  `reboot`, filesystem tools, `ip`, firewall tools, `docker`, `rm`, `mv`, `chmod`,
  `chown`, `kill`, and `pkill`.
- Always refuses obvious vehicle-control command names such as `mcu_bridge`,
  `can_actuator`, `serial_actuator`, `cansend`, `candump`, and motor/steer/brake/throttle
  control names.
- Keeps ordinary read-only commands working.

Validation commands:

```powershell
.venv\Scripts\python -m py_compile tools\board_run.py

.venv\Scripts\python tools\board_run.py --help

.venv\Scripts\python tools\board_run.py 'whoami'

.venv\Scripts\python tools\board_run.py 'echo rm'

.venv\Scripts\python tools\board_run.py 'echo mcu_bridge'

.venv\Scripts\python tools\dtof_live_preflight.py --out logs\dtof_live_preflight_boardrun_guard_check.json --summary-out logs\dtof_live_preflight_boardrun_guard_check_summary.txt
```

Safety status:

- `whoami` is read-only and returned `root`.
- `echo rm` was chosen so that even if the guard failed, the remote command would only
  echo text; the guard correctly blocked it before SSH execution.
- `echo mcu_bridge` was chosen so that even if the guard failed, the remote command would
  only echo text; the guard correctly blocked it before SSH execution.
- The final preflight used fixed read-only board/VM checks.
- No board dToF sample was started.
- No VM UDP listener was started.
- No actuator or chassis-control process was started.

Observed guard results:

```text
Refusing to send a potentially important or dangerous board command.
Matched risk rule: \brm\b

Refusing to send a board command that appears to target a vehicle control path.
Matched forbidden control rule: \bmcu_bridge\b
```

Observed preflight after the guard change:

```text
DTOF_LIVE_PREFLIGHT_SUMMARY
timestamp=2026-06-02T17:44:35
pass=True
issues=[]
warnings=["VM TCP 8765 is occupied, usually by the existing Foxglove bridge"]
board_unsafe_process_count=0
vm_unsafe_process_count=0
board_udp_2368_occupied=False
vm_udp_2368_occupied=False
board_hash_ok=sample_dtof_official_j4cfg_dbg,sample_dtof_official_line_dump_cp_dbg,sample_dtof_official_vi_user_replay_dev3_be_line_chn_dbg,dtof_init.sh,dtof.ini,gs1860_register.ini
```

Artifacts:

```text
logs/dtof_live_preflight_boardrun_guard_check.json
logs/dtof_live_preflight_boardrun_guard_check_summary.txt
```

Conclusion:

- The board SSH wrapper now enforces the same safety posture required by the workspace
  rules.
- Current dToF preflight still passes with the new board command guard.

## 53. 2026-06-02 clear_j4_live LINE dump baseline

After the operator cleared the dToF field of view, a perception-only clear-scene
baseline was captured with the official J4 LINE-dump binary.

Command:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition clear_j4_live --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Safety status:

- Preflight passed before the live run.
- The only warning was that VM TCP 8765 was already occupied, consistent with the
  existing Foxglove bridge.
- The run started only the board dToF sample and the VM UDP checker.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle,
  STM32/chassis-control, or other actuator path was started.
- The car did not move.

Artifacts:

```text
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_preflight.json
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_preflight_summary.txt
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_commands.txt
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_board.log
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_vm.log
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_report.json
logs/dtof_phase1_clear_j4_live_line_dump_cp_official_20260602_175231_report.report_stdout.log
artifacts/dtof_line_dump_clear_j4_live_20260602_175231/
```

Observed board-side evidence:

```text
DtofInit success!!!
pixfmt=21
compress=4
raw_nonzero.count=12
raw_nonzero.median=12429
raw_max.median=4095
out_mid.median=2
out_eq_2.median=1199
all_2mm_frame_count=2
classification.gate=line_compressed_stream_not_decoded
```

Observed VM UDP evidence:

```text
PACKETS=20
GOOD_SIZE_4873=20
GOOD_HEADER_40x30=20
GOOD_PIXEL_NUMBER_1200=20
GOOD_FRAME_RATE_30=20
DTOF_UDP_CHECK=PASS
DTOF_UDP_STRICT_CHECK=PASS
VALIDISH_DEPTH_PACKETS=18
ALL_2MM_PACKETS=2
VALID_NON_SENTINEL_PACKETS=18
NEAR_MAJORITY_LT_1000_PACKETS=5
NEAR_MEDIAN_LT_1000_PACKETS=3
```

Observed LINE artifact evidence:

```text
downloaded_frames=4
frame_size=110112
width=2560
height=31
stride0=3552
pixel_format=21
compress_mode=4
row1_nonzero=342
MASK_FRAME_COUNT=4
MASK_BEST_START_WORD_COUNTS=[[4, 4]]
MASK_MATCH_40X64=True
```

Interpretation:

- This is not evidence that the dToF is already reporting a valid near object.
- Clear-scene UDP packets have the official 4873-byte / 40x30 / 1200-pixel format,
  so the UDP transport path is alive.
- VI raw buffers are not zero; pixfmt 21 with LINE compression is present on J4.
- DtofProcess/UDP output is still dominated by the 2mm sentinel at the center and
  across almost all pixels.
- The few sub-1m non-sentinel values in a clear scene are not a valid near-distance
  majority result.
- This clear baseline is useful only as the reference for the next `near30cm_j4_live`
  capture. The decisive test is whether the LINE artifacts and/or DtofProcess output
  change when a real obstruction is placed within 30cm.

## 54. 2026-06-02 near30cm_j4_live LINE dump and clear-vs-near comparison

After the operator placed an obstruction within 30cm of the dToF field of view, a
perception-only near-scene capture was run with the same official J4 LINE-dump
binary.

Command:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition near30cm_j4_live --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Comparison command:

```powershell
.venv\Scripts\python tools\dtof_line_latest_compare.py clear_j4_live near30cm_j4_live
```

Safety status:

- Preflight passed before the live run.
- The only warning was the existing VM TCP 8765 Foxglove bridge listener.
- The run started only the board dToF sample and the VM UDP checker.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle,
  STM32/chassis-control, or other actuator path was started.
- The car did not move.

Near-capture artifacts:

```text
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_preflight.json
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_preflight_summary.txt
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_commands.txt
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_board.log
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_vm.log
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_report.json
logs/dtof_phase1_near30cm_j4_live_line_dump_cp_official_20260602_180020_report.report_stdout.log
artifacts/dtof_line_dump_near30cm_j4_live_20260602_180019/
```

Comparison artifacts:

```text
logs/dtof_line_compare_clear_j4_live_vs_near30cm_j4_live_20260602_180044.json
logs/dtof_line_compare_clear_j4_live_vs_near30cm_j4_live_20260602_180044_summary.txt
logs/dtof_line_compare_clear_j4_live_vs_near30cm_j4_live_20260602_180044_decision.json
logs/dtof_line_compare_clear_j4_live_vs_near30cm_j4_live_20260602_180044_decision_summary.txt
```

Observed near-capture board-side evidence:

```text
DtofInit success!!!
pixfmt=21
compress=4
raw_nonzero.count=12
raw_nonzero.median=12429
raw_max.median=4095
out_mid.median=2
out_eq_2.median=1199
all_2mm_frame_count=2
classification.gate=line_compressed_stream_not_decoded
```

Observed near-capture VM UDP evidence:

```text
PACKETS=20
GOOD_SIZE_4873=20
GOOD_HEADER_40x30=20
GOOD_PIXEL_NUMBER_1200=20
GOOD_FRAME_RATE_30=20
DTOF_UDP_CHECK=PASS
DTOF_UDP_STRICT_CHECK=PASS
VALIDISH_DEPTH_PACKETS=18
ALL_2MM_PACKETS=2
VALID_NON_SENTINEL_PACKETS=18
NEAR_MAJORITY_LT_1000_PACKETS=5
NEAR_MEDIAN_LT_1000_PACKETS=3
```

Observed LINE artifact evidence:

```text
near_frame_count=4
near_frame_size=110112
near_width=2560
near_height=31
near_stride0=3552
near_pixel_format=21
near_compress_mode=4
near_compress_param_sha16=647057ba5f7082a0
near_frame_sha16=fda5240e7d910620,d8e543f2d83b8423,f2744b52f387d723,bc5cacdf4dc2c143
```

Clear-vs-near comparison:

```text
decision=NO_LINE_SCENE_CHANGE_OBSERVED
raw_line_scene_change=no
changed_byte_offsets=0
changed_word_offsets=0
mask_delta_count=0
zero_changed_byte_offsets=True
```

Interpretation:

- The 30cm obstruction did not produce a valid near-distance result.
- The near capture has the same UDP depth behavior as the clear baseline: mostly 2mm
  sentinel output, with only sparse non-sentinel pixels and no majority near result.
- The downloaded LINE frames are byte-identical to the clear baseline for all four
  dumped frames.
- Because the raw LINE artifacts did not change at all under a controlled near
  obstruction, this is not a ROS threshold or visualization issue.
- Priority should shift to physical light path, exact obstruction/FOV coverage, J3/J4
  MIPI/I2C mapping, trigger/config, power, or whether the current VI pipe is seeing a
  static/generated LINE pattern rather than scene-dependent dToF returns.

## 55. 2026-06-02 covered_j4_live full-cover LINE dump and clear-vs-covered comparison

After the operator fully covered the dToF transmit/receive window area, a third
perception-only capture was run with the same official J4 LINE-dump binary.

Command:

```powershell
.venv\Scripts\python tools\capture_dtof_line_condition.py --condition covered_j4_live --binary sample_dtof_official_line_dump_cp_dbg --seconds 8 --max-packets 20
```

Comparison command:

```powershell
.venv\Scripts\python tools\dtof_line_latest_compare.py clear_j4_live covered_j4_live
```

Safety status:

- Preflight passed before the live run.
- The only warning was the existing VM TCP 8765 Foxglove bridge listener.
- The run started only the board dToF sample and the VM UDP checker.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle,
  STM32/chassis-control, or other actuator path was started.
- The car did not move.

Covered-capture artifacts:

```text
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_preflight.json
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_preflight_summary.txt
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_commands.txt
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_board.log
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_vm.log
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_report.json
logs/dtof_phase1_covered_j4_live_line_dump_cp_official_20260602_180459_report.report_stdout.log
artifacts/dtof_line_dump_covered_j4_live_20260602_180458/
```

Comparison artifacts:

```text
logs/dtof_line_compare_clear_j4_live_vs_covered_j4_live_20260602_180522.json
logs/dtof_line_compare_clear_j4_live_vs_covered_j4_live_20260602_180522_summary.txt
logs/dtof_line_compare_clear_j4_live_vs_covered_j4_live_20260602_180522_decision.json
logs/dtof_line_compare_clear_j4_live_vs_covered_j4_live_20260602_180522_decision_summary.txt
logs/dtof_line_compare_near30cm_j4_live_vs_covered_j4_live_20260602_180705.json
logs/dtof_line_compare_near30cm_j4_live_vs_covered_j4_live_20260602_180705_summary.txt
logs/dtof_line_compare_near30cm_j4_live_vs_covered_j4_live_20260602_180705_decision.json
logs/dtof_line_compare_near30cm_j4_live_vs_covered_j4_live_20260602_180705_decision_summary.txt
```

Observed covered-capture board-side evidence:

```text
DtofInit success!!!
pixfmt=21
compress=4
raw_nonzero.count=12
raw_nonzero.median=12429
raw_max.median=4095
out_mid.median=2
out_eq_2.median=1199
all_2mm_frame_count=2
classification.gate=line_compressed_stream_not_decoded
```

Observed covered-capture VM UDP evidence:

```text
PACKETS=20
GOOD_SIZE_4873=20
GOOD_HEADER_40x30=20
GOOD_PIXEL_NUMBER_1200=20
GOOD_FRAME_RATE_30=20
DTOF_UDP_CHECK=PASS
DTOF_UDP_STRICT_CHECK=PASS
VALIDISH_DEPTH_PACKETS=18
ALL_2MM_PACKETS=2
VALID_NON_SENTINEL_PACKETS=18
NEAR_MAJORITY_LT_1000_PACKETS=5
NEAR_MEDIAN_LT_1000_PACKETS=3
```

Observed LINE artifact evidence:

```text
covered_frame_count=4
covered_frame_size=110112
covered_width=2560
covered_height=31
covered_stride0=3552
covered_pixel_format=21
covered_compress_mode=4
covered_compress_param_sha16=647057ba5f7082a0
covered_frame_sha16=fda5240e7d910620,d8e543f2d83b8423,f2744b52f387d723,bc5cacdf4dc2c143
```

Clear-vs-covered comparison:

```text
decision=NO_LINE_SCENE_CHANGE_OBSERVED
raw_line_scene_change=no
changed_byte_offsets=0
changed_word_offsets=0
mask_delta_count=0
zero_changed_byte_offsets=True
```

Near-vs-covered comparison:

```text
decision=NO_LINE_SCENE_CHANGE_OBSERVED
raw_line_scene_change=no
changed_byte_offsets=0
changed_word_offsets=0
mask_delta_count=0
zero_changed_byte_offsets=True
```

Interpretation:

- Fully covering the dToF window did not change either the DtofProcess/UDP output or
  the dumped LINE raw frames.
- Clear, 30cm-near, and full-cover captures all produced the same first four LINE
  frame SHA prefixes: `fda5240e7d910620`, `d8e543f2d83b8423`,
  `f2744b52f387d723`, and `bc5cacdf4dc2c143`.
- Clear-vs-near, clear-vs-covered, and near-vs-covered all report zero changed byte
  offsets, zero changed word offsets, and zero mask deltas.
- This strongly argues that the current captured VI/LINE path is not receiving
  scene-dependent dToF returns.
- Do not tune ROS thresholds or obstacle logic to mask this. The next root-cause work
  should target the dToF physical light path, J3/J4 MIPI/I2C routing, trigger/config,
  power, or the possibility that the current pipe is exposing a static/generated LINE
  pattern instead of live dToF histogram data.
## 56. 2026-06-02 clean RAW10/NONE-at-creation route2 prep

Continuation work re-read `docs/dtof_debug_summary_20260602.md` and this full plan.
The current authoritative direction is no longer random RAW10/RAW12/NONE/LINE sweeps:
the dToF hardware and `DtofProcess` are proven by good transition frames, while steady
capture is blocked by the SS928 `BYPASS_BE` raw-dump path. The next software experiment
is the summary's route2: create the GS1860 pipe as `RAW10 + NONE` from startup on clean
source and test J3/case1.

Local-only prep completed:

```text
tools/vm_build_official_raw10_create_clean.sh
docs/dtof_raw10_create_clean_runbook_20260602.md
```

Script behavior:

- Extracts a fresh SDK zip into a new VM build directory.
- Patches only the throwaway build tree.
- Disables `rtsp_set_client_event_cb(...)` only for the VM's old `libxoprtsp.a`.
- Adds `pipe_attr.bit_width = OT_DATA_BIT_WIDTH_10` in both GS1860 raw10 pipe blocks.
- Builds with
  `-DDTOF_FORCE_RAW10_NONE -DDTOF_KEEP_PIPE_ATTR -DDTOF_RAW10_CREATE_CLEAN`.
- Produces non-overwriting binary `sample_dtof_raw10_create_clean`.
- Verifies marker string `DTOF_RAW10_CREATE_CLEAN` in the binary.

Local anchor validation:

```text
raw10_pipe_blocks 2
rtsp_line True
sample_marker True
sample_get_char_anchor True
one_dtof_anchor_count 1
makefile_extra_hook True
makefile_marker True
```

No board/VM state-changing command was run in this prep step.

Pending commands requiring explicit approval:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"

.venv\Scripts\python tools\vm_ssh_run.py --timeout 120 run "sshpass -p ebaina scp -p -o StrictHostKeyChecking=no <BINARY_FROM_BUILD_OUTPUT> root@192.168.137.2:/opt/sample/official_dtof/sample_dtof_raw10_create_clean"

.venv\Scripts\python tools\board_run.py "cd /opt/sample/official_dtof && sha256sum sample_dtof_raw10_create_clean && ls -l sample_dtof_raw10_create_clean"

.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition steady_raw10_create_clean_j3 --binary sample_dtof_raw10_create_clean --case 1 --seconds 35 --max-packets 120
```

Purpose:

- Test whether clean-source GS1860 J3/case1 can deliver steady non-zero raw and usable
  UDP depth when `RAW10 + NONE` is set at pipe creation and the later dump-attr switch is
  avoided.

Risk:

- Upload/build/deploy commands change VM or board filesystem state.
- The final capture starts only the board dToF perception sample and VM UDP listener.
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

## 57. 2026-06-02 raw10_create_clean VM build attempt failed before compile, script corrected

The previously approved VM-only build sequence was executed:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"
```

Safety status:

- Only VM `/tmp` and a VM throwaway build directory were changed.
- No board file was deployed or modified.
- No board dToF sample was started.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  STM32/chassis-control path was started.

The build failed before compilation with:

```text
expected at least two RAW10 pipe blocks, found 0
```

Artifact:

```text
logs/vm_ssh_20260602_193208_5e01fe0e.log
```

Root cause:

- The first version of `tools/vm_build_official_raw10_create_clean.sh` searched for
  diagnostic `DTOF_FORCE_RAW10_NONE` pipe blocks that exist only in a previously modified
  source tree.
- The fresh SDK zip used by this clean build route does not contain those blocks.
- The route2 test was therefore not executed; only the patch script failed.

Local correction now present in `tools/vm_build_official_raw10_create_clean.sh`:

- Patch the clean SDK directly rather than looking for pre-existing local macro blocks.
- Change `sample_dtof_get_default_vb_config()` to accept `sns_type` and allocate GS1860 raw
  VB as `RAW10 + NONE + bit_width 10`.
- Insert GS1860 `RAW10 + NONE + bit_width 10` overrides into both default VI pipe init
  functions in `src/common/sample_comm_vi.c`.
- Insert the same override after both GS1860 `OT_VI_PIPE_BYPASS_BE` assignments in
  `sample_dtof_get_one_dtof_sensor_vi_cfg()`.
- A read-only check of the failed VM extraction showed that clean `dtof_dumpraw.c` does
  not contain `DTOF_KEEP_PIPE_ATTR` support:
  `logs/vm_ssh_20260602_193919_61c30d2b.log`.
- The script now injects an `#ifndef DTOF_KEEP_PIPE_ATTR` guard around the
  `ss_mpi_vi_set_pipe_attr()` block in `set_dump_pipe_attr()`, so the compiled
  `-DDTOF_KEEP_PIPE_ATTR` flag actually prevents the known-bad runtime pipe-attribute
  switch.
- Keep the VM link workaround for `rtsp_set_client_event_cb(...)`, the marker
  `DTOF_RAW10_CREATE_CLEAN`, and the non-overwriting output name
  `sample_dtof_raw10_create_clean`.
- The clean VM extraction does not contain the local `g_camera_venc_started` marker used
  by an earlier script version. Read-only evidence:
  `logs/vm_ssh_20260602_194154_9e00e1a9.log` and
  `logs/vm_ssh_20260602_194215_af87b14a.log`. The current script anchors the marker after
  `g_sig_flag` instead.

The next VM upload/build requires fresh explicit approval because the script content
changed:

```powershell
.venv\Scripts\python tools\vm_ssh_run.py put-text tools\vm_build_official_raw10_create_clean.sh /tmp/vm_build_official_raw10_create_clean.sh

.venv\Scripts\python tools\vm_ssh_run.py --timeout 300 run "bash /tmp/vm_build_official_raw10_create_clean.sh"
```

Expected corrected patch marker:

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

## 58. 2026-06-02 route1 open_camera source pass while route2 awaits approval

No VM/board state was changed. A local read-only source pass prepared the alternate
open_camera route in case route2 fails or remains blocked waiting for approval.

Relevant local files:

```text
vendor/HiEuler_open_camera_unzip/open_camera-master/README.md
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/readme.txt
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/Makefile
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c
vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/dtof_dumpraw.c
```

Findings:

- README says `sample_vio` implements GS1860 dToF distance output viewable from a host
  point-cloud tool.
- `imx347.c` already has the recovery setting `SUPPORT_RGB 0` and `SUPPORT_DTOF 1`.
- The route1 J3/dtof0 command should use sns index 1:

```sh
./sample_vio 1 192.168.137.100
```

- `sns_info[1].i2c_bus = 5`; the dtof-only code subtracts one and reaches the J3/i2c4
  GS1860 branch. That branch uses `vi_dev=2`, `vi_pipe=2`, `mipi_dev=2`, and lane `4`.
- This is a meaningful topology change versus MPP `sample_dtof` case1, which used pipe 1.
- open_camera `dtof_dumpraw.c` still performs RAW10/NONE pipe-attr preparation, so this
  route is not guaranteed; its value is the different VI/MIPI mapping and official
  bring-up sequence.

Safety status:

- Local read-only source inspection and documentation only.
- No build, deploy, board command, VM upload, dToF sample, MCU bridge, CAN actuator,
  serial actuator, motor, steering, brake, throttle, or STM32/chassis-control path was
  started.

Route1 runbook added:

```text
docs/dtof_open_camera_route1_runbook_20260602.md
```

Additional read-only VM evidence:

```text
logs/vm_ssh_20260602_195518_ad58932b.log
logs/vm_ssh_20260602_195518_455f27cb.log
logs/vm_ssh_20260602_195518_9f81066c.log
logs/vm_ssh_20260602_195551_e346bde5.log
logs/vm_ssh_20260602_195551_fe6bebb6.log
logs/vm_ssh_20260602_195551_f629a2dc.log
logs/vm_ssh_20260602_195551_49945e88.log
logs/vm_ssh_20260602_195804_b7b921ce.log
```

Important route1 risk note:

- `init_dtof_cfg.sh` performs `bspmm 0x0102F014C 0x1200` and toggles GPIO96 through
  `/sys/class/gpio`.
- Running it is board state-changing and requires separate explicit approval with
  `board_run.py --allow-risk`.
- The route1 live capture should use `tools/capture_dtof_udp_pair.py` or a manual paired
  VM UDP + board `sample_vio` fallback. `tools/run_dtof_phase1_condition.py` remains
  specialized for `/opt/sample/official_dtof` and `sample_dtof*`.

Local-only helper added:

```text
tools/capture_dtof_udp_pair.py
```

Validation:

```powershell
.venv\Scripts\python -m py_compile tools\capture_dtof_udp_pair.py
.venv\Scripts\python tools\capture_dtof_udp_pair.py --help
.venv\Scripts\python tools\capture_dtof_udp_pair.py --condition bad --binary mcu_bridge --preflight-only
```

Observed:

- syntax check passed;
- help printed normally;
- non-whitelisted `mcu_bridge` was rejected before any board/VM command could be run.

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

Result:

```text
pass=True
issues=[]
PREFLIGHT_ONLY=1
Not starting VM UDP capture or board sample.
```

## 59. 2026-06-02 local route2 patch dry-run checker

Local-only tool added:

```text
tools/dtof_raw10_create_clean_patch_check.py
```

Command:

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

- The corrected route2 script's clean-source anchors exist in the local clean SDK zip.
- The dry-run now simulates the patch in memory and verifies the post-patch signature,
  call, GS1860 overrides, keepattr guard, marker, and Makefile hook.
- The clean Makefile lacks `CFLAGS += $(EXTRA_CFLAGS)`, so hook insertion remains needed.
- This dry-run is local and read-only. It did not upload to the VM, build, deploy, run any
  board command, or start any dToF/actuator/chassis process.

## 60. 2026-06-02 route2 RAW10_CREATE clean execution result

Safety status:

- Only VM build/deploy, board dToF perception sample, and VM UDP listener were used.
- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  STM32/chassis-control path was started.
- No physical movement was requested or performed.

Build and deployment:

```text
logs/vm_ssh_20260602_202803_aa91e64d.log
sample_dtof_raw10_create_clean
SHA256=10016ad372d92a5c3f8a835eb777c9d5a8cae82eccac79e4fa0fb10a895ab0be
BUILD_DIR=/home/ebaina/official_dtof_raw10_create_clean_20260602_202802
```

The first live run showed a harness problem, not a dToF conclusion:

```text
logs/dtof_phase1_steady_raw10_create_clean_j3_20260602_202854_report.json
classification.gate=startup_failed
```

Cause: the helper launched `timeout <seconds> ./sample_dtof...` with closed stdin, so the
official `sample_pause()` returned immediately after printing `press enter key to exit`.
`tools/run_dtof_phase1_condition.py` was fixed to keep stdin open and send a delayed
newline:

```sh
( sleep <seconds>; printf "\n" ) | timeout <seconds+10> ./sample_dtof... <case> <ip>
```

After the harness fix, the clean RAW10_CREATE binary ran normally but UDP was still all
2mm:

```text
logs/dtof_phase1_steady_raw10_create_clean_j3_holdstdin_20260602_203036_report.json
PACKETS=120
GOOD_SIZE_4873=120
ALL_2MM_PACKETS=120
VALID_NON_SENTINEL_PACKETS=0
```

Because the non-debug binary could not expose raw stats, a debug variant was built with
the same clean source patches plus `artifacts/official_dtof_dumpraw_keepattr_debug.c`:

```text
logs/vm_ssh_20260602_203319_e87ab619.log
sample_dtof_raw10_create_clean_dbg
SHA256=3888faf6a28b37440bc9a16e90c8b9c50b9f31c05d06d8344aec34a3eaef000d
BUILD_DIR=/home/ebaina/official_dtof_raw10_create_clean_20260602_203318
```

Decisive debug result:

```text
logs/dtof_phase1_steady_raw10_create_clean_dbg_j3_20260602_203420_report.json
classification.gate=raw_zero_from_start
debug_frame_count=12
pixfmts=[20]
compress_modes=[0]
raw_nonzero.median=0
raw_max.median=0
out_eq_2.median=1200
ALL_2MM_PACKETS=120
```

Representative board frame:

```text
[DTOF_FRAME] frame=1 w=2560 h=31 stride0=3200 pixfmt=20 compress=0 row_sum32=737/0/0
[DTOF_DBG] frame=1 raw_max=0 raw_nonzero=0 out_max=2 out_eq_2=1200 out_mid=2
```

Conclusion:

- Route2 disproves the hypothesis that creating the MPP GS1860 pipe as `RAW10 + NONE`
  from startup fixes the steady raw path.
- The raw delivered to user space is zero from frame 1, so the all-2mm UDP output is
  expected and cannot be fixed by ROS thresholds.
- Do not run the near-distance gate for this route; it cannot produce true near output
  while raw is zero.

Next action:

- Continue with route1 open_camera dtof-only topology. The useful difference is
  `vi_pipe=2`/`mipi_dev=2`/official open_camera bring-up, not another MPP pipe1 RAW10
  tweak.
- `tools/capture_dtof_udp_pair.py` was also fixed to use delayed newline stdin before
  route1 live runs.

## 2026-06-02 21:40 addendum - route1 dtof-only attempt and restored official sanity

Safety status for this block:

- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control program was started.
- Only board/VM perception binaries, media-stack reload, compilation, deployment, and
  UDP logging were used.
- The car did not move.

The open_camera-derived dtof-only path was useful diagnostically but is not the next
production route:

```text
logs/dtof_udp_pair_debug2_fullcover_os08a20_dtofonly_j3_20260602_212238_board.log
sample_comm_vi_start_vi dtof ret=0x0
dtof_init failed: Open /dev/ot_i2c_drv-255 error
```

This proved the earlier `sample_comm_vi_start_vi` blockage could be passed, but skipping
the whole ISP start path also skipped GS1860 sensor bus setup. A minimal explicit
`sample_comm_isp_bind_sns(pipe, GS1860, i2c4)` fix then passed EEPROM/DtofInit:

```text
logs/dtof_udp_pair_debug3_fullcover_os08a20_dtofonly_bind_i2c_j3_20260602_212611_board.log
sample_comm_isp_bind_sns dtof bus=4 ret=0x0
DtofInit success!!!
vi_bayerdump failed: 0xa0108016
```

Further route1 variants showed:

- Manual `gs1860_init()` needed sensor callback registration, but even after callback
  registration the pipe still did not produce frames.
- Changing route1 from open_camera `pipe2/clk2/rst2` to official `pipe1/clk1/rst1` still
  timed out in `Get VI Pipe 1 frame err`.
- Re-enabling the official ISP mem/init path without the skip macro failed with
  `OT_MPI_ISP_Init failed with 0xa01c8040` after adding the official BE-bypass field.

Representative logs:

```text
logs/dtof_udp_pair_debug5_fullcover_os08a20_dtofonly_register_sns_j3_20260602_213134_board.log
logs/dtof_udp_pair_debug6_fullcover_os08a20_dtofonly_official_pipe1_j3_20260602_213422_board.log
logs/dtof_udp_pair_debug8_fullcover_os08a20_dtofonly_official_vi_cfg_j3_20260602_213845_board.log
```

Conclusion: do not spend more time on the open_camera-derived dtof-only outer shell until
there is a new, specific hypothesis. It does not yet preserve the known-good official
packet path and has introduced media-stack residual state during failure cleanup.

After these failed starts, even official case1 reported stale ISP state:

```text
logs/dtof_udp_pair_sanity_fullcover_official_case1_after_custom_20260602_213949_board.log
ISP[1] already inited
OT_MPI_ISP_MemInit failed with 0xa01c800c
```

The media stack was reloaded with the perception-only command:

```sh
cd /opt/ko && ./load_ss928v100 -a
```

Post-reload official case1 sanity recovered UDP and reproduced the decisive steady-state
failure:

```text
logs/dtof_udp_pair_sanity2_fullcover_official_case1_after_media_reload_20260602_214133_board.log
logs/dtof_udp_pair_sanity2_fullcover_official_case1_after_media_reload_20260602_214133_vm.log
PACKETS=80
GOOD_SIZE_4873=80
GOOD_HEADER_40x30=80
GOOD_PIXEL_NUMBER_1200=80
DTOF_UDP_STRICT_CHECK=PASS
```

Under full cover, the first two frames had real near valid pixels, then the official
RAW10/NONE switch zeroed raw from frame 3 onward:

```text
frame=1 pixfmt=21 compress=4 raw_nonzero=8220 out_max=179 out_eq_2=1170
frame=2 pixfmt=21 compress=4 raw_nonzero=8220 out_max=179 out_eq_2=1170
frame=3 pixfmt=20 compress=0 raw_nonzero=0 out_max=2 out_eq_2=1200
```

VM packet summaries confirm the same:

```text
DEPTH_SUMMARY seq=1 valid=30 valid_median=158.5 valid_lt1000=30
DEPTH_SUMMARY seq=2 valid=30 valid_median=158.5 valid_lt1000=30
DEPTH_SUMMARY seq=3 valid=0 center=2
```

Current high-confidence conclusion:

- The module, I2C/EEPROM, DtofInit, UDP transport, and official packet format are alive.
- The near-cover scene can produce true near output at about 158 mm in the first two
  valid frames.
- The current blocker is the steady-state user-space dump path: after `vi_bayerdump()`
  changes the pipe to `RAW10 + NONE`, raw becomes zero and DtofProcess outputs all 2 mm.
- ROS/Foxglove thresholds are not the fix.

Next action:

- Stay on the official `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof`
  baseline.
- Build a tightly scoped official diagnostic/fix variant around `dtof_dumpraw.c` that
  either avoids the raw-zeroing pipe-attribute transition or captures/decompresses the
  original `RAW12 + LINE` data correctly before DtofProcess.
- Judge success only by steady-state UDP frames where most valid pixels under a 30 cm
  or full-cover near obstruction are `<1 m`, not by the first two pre-switch frames.

## 2026-06-02 21:45 addendum - full-cover line dump still scene-invariant

Safety status for this block:

- No MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
  chassis-control program was started.
- Only board/VM perception samples, UDP capture, raw-line download, and local artifact
  comparison were used.
- The car did not move.

After the media-stack reload, the official `line_dump_cp` diagnostic was run under the
user-confirmed full-cover condition:

```text
logs/dtof_udp_pair_fullcover_official_line_dump_cp_after_media_reload_20260602_214538_board.log
logs/dtof_udp_pair_fullcover_official_line_dump_cp_after_media_reload_20260602_214538_vm.log
```

It kept `pixfmt=21 compress=4` (`RAW12 + LINE`) and raw stayed non-zero:

```text
[DTOF_DBG] dump_source=pipe keep vi_pipe 1 attr pixfmt=21 compress=4
raw_nonzero median ~=12421, raw_max=4095
PACKETS=80 GOOD_SIZE_4873=80 GOOD_HEADER_40x30=80
ALL_2MM_PACKETS=73 VALID_NON_SENTINEL_PACKETS=7 NEAR_MEDIAN_LT_1000_PACKETS=0
```

This confirms the UDP path and official packet format are still stable, but the current
LINE data is not being converted into a valid near-distance result.

A fresh downloadable full-cover line dump was then captured:

```text
logs/dtof_phase1_fullcover_after_reload_verify_line_line_dump_cp_official_20260602_214840_report.json
artifacts/dtof_line_dump_fullcover_after_reload_verify_line_20260602_214840
```

The artifact has the expected 40x64 mask structure, but comparing it with earlier
controlled `clear`, `near30cm`, and `covered` captures produced no scene-dependent raw
change:

```text
logs/dtof_line_compare_clear_vs_fullcover_after_reload_20260602_214840_summary.txt
logs/dtof_line_compare_near_vs_fullcover_after_reload_20260602_214840_summary.txt
logs/dtof_line_compare_covered_vs_fullcover_after_reload_20260602_214840_summary.txt

changed_byte_offsets=0
changed_word_offsets=0
mask_delta_count=0
compress_param_sha16=647057ba5f7082a0
```

Updated conclusion:

- The SS928/official sample can initialize GS1860, DtofInit, and UDP 4873-byte output.
- The normal official RAW10/NONE dump switch still zeros raw after the initial frames.
- Keeping RAW12/LINE preserves non-zero bytes, but the captured LINE measurement rows are
  invariant across clear/near/covered/full-cover tests.
- Therefore this is no longer only a user-space unpack problem. The next root-cause split
  must include physical light path, J3/J4 mapping, trigger/config, power, or MIPI routing,
  because the currently captured raw stream does not show the user's near obstruction.
- Do not claim the first two ~158 mm pre-switch frames as steady-state success. They are
  useful clues, but the reproducible raw artifacts do not yet prove scene response.

## 2026-06-02 external-source note - Taobao bundle vs public sample coverage

The user clarified that the OS08A20 + SS-LD-AS01/GS1860 dToF combination is sold by
the official Taobao store. Treat that as evidence that the hardware combination should
be vendor-supported, but keep it separate from public-source availability.

Current public/local source search result:

- The closest official baseline remains
  `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof`. It supports both
  `OV_OS08A20_MIPI_8M_30FPS_12BIT` and
  `HISI_GS1860_MIPI_1M_30FPS_10BIT`, and exposes sensor0 + dtof0/dtof1 cases, but it is
  a generic configurable MPP sample rather than a proven turnkey package for the exact
  OS08A20 + SS-LD-AS01 + current J3/J4 wiring.
- `vendor/HiEuler_open_camera_unzip/open_camera-master` is a useful whole-machine
  mapping reference, but its public code is centered on IMX347 + GS1860, not OS08A20.
- No public package has been found yet that explicitly names the exact sold combination
  and provides a matching board image, MIPI/I2C/J3/J4 routing table, `sample_dtof`
  source/binary, `dtof.ini`, `gs1860_register.ini`, and a near-distance acceptance log.

Vendor-support request should ask for the exact support bundle for the purchased SKU:

- Board image name/version and checksum.
- Matching source or binary for OS08A20 + SS-LD-AS01/GS1860 on SS928/Euler Pi.
- Exact sensor mapping: J3/J4, sensor index, MIPI dev/lane, VI dev/pipe, I2C bus/address,
  reset/clock GPIO, and whether dtof is expected on sensor2 or sensor3.
- Expected `SENSOR0_TYPE`, `SENSOR2_TYPE`, `SENSOR3_TYPE`, `dtof.ini`, and
  `gs1860_register.ini`.
- Factory verification command and a log showing a 30 cm obstruction producing mostly
  `<1 m` valid depth over UDP 2368 / 4873-byte packets.

Product identity note:

- Do not treat the current dToF as a Slamtec/思岚 RPLIDAR-class device unless the vendor
  explicitly provides different SKU evidence.
- The working identifiers in this project remain SS-LD-AS01 / GS1860 /
  `HISI_GS1860_MIPI_1M_30FPS_10BIT`.
- Public search evidence points the `SS-LD` / `AS01` naming toward SMiTSense/国微感知
  lidar/dToF products and Ebaina's cooperation ecosystem, not toward Slamtec's serial/USB
  RPLIDAR SDK path.

Hardware-integrity hypothesis:

- A missing small capacitor/resistor on the back of the SS-LD-AS01 module is a plausible
  root cause and should not be dismissed.
- The current evidence does not look like a totally dead module: I2C/EEPROM, DtofInit,
  UDP 2368, and 4873-byte packets are alive, and the first pre-switch frames can contain
  near-distance-like values.
- However, a missing passive component in the VCSEL/LD driver, SPAD/AFE bias/filtering,
  sync/trigger, MIPI termination, or local power-decoupling path could still leave digital
  initialization alive while making scene-dependent depth unstable or invariant.
- This hardware hypothesis is consistent with the latest controlled captures where
  RAW12/LINE bytes remained non-zero but did not change across clear/near/full-cover
  conditions.
- Next non-software check, before more blind code variants: compare high-resolution front
  and back photos of the user's dToF module against an official product photo or a known
  good module, looking for missing pads, cracked MLCCs, lifted resistors, solder bridges,
  flex/connector damage, or contamination near the optics.
- A same-family GS1860/dToF backside reference image was found in the local official
  `dtof_sensor_driver` documentation:
  `vendor/dtof_sensor_driver-master/doc/嵌入式dToF模组开发学习资料v1.1/picture/image-20240318174940602.png`.
  A cropped comparison image was saved as
  `artifacts/dtof_gs1860_backside_crop.png`.

Screenshot/resource follow-up:

- The Taobao detail screenshot lists official resource channels:
  `https://www.ebaina.com/ai/58`, `https://www.ebaina.com/ask/create`,
  `https://gitee.com/hieulerpi`, and Baidu Pan
  `https://pan.baidu.com/s/1Pi1EtlwUkBpV-VHDWK29Sw?pwd=515w`.
- The official online product page confirms customer-facing resource entries for the
  board, including MPP sample, adapted SDK, factory firmware, driver packages, and
  documentation.
- A particularly relevant download page was found:
  `https://www.ebaina.com/down/240000038948`
  ("海鸥派 sample_dtof 采集数据的点云图显示"). The public metadata says it is for
  visualizing `.raw` depth data captured by `sample_dtof`, but the actual download is
  login/E-coin gated.
- This strengthens the conclusion that the exact sold bundle may have support material
  outside the public Gitee repositories. The next information target is the Baidu Pan
  package or logged-in Ebaina downloads, not another blind code-variant loop.

## 2026-06-02 route correction - fix standalone dToF first

The user corrected the priority model: because standalone dToF still does not produce
stable near-depth under close obstruction, the current blocker is not the absence of an
OS08A20 + dToF combined sample. The RGB camera combination is downstream and should not
be used to explain the current single-dToF failure.

Correct current scope:

- Keep OS08A20/case3/RTSP out of the root-cause path until standalone dToF passes.
- Treat the official dToF materials as the authoritative baseline:
  - `vendor/dtof_sensor_driver-master` for GS1860 module specs, UDP/UVC/UART protocol,
    4873-byte packet layout, factory config tool/docs, and Taurus dToF examples.
  - `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof` for the SS928 MIPI/VI
    `sample_dtof`, `dtof_dumpraw.c`, `dtof.ini`, and `gs1860_register.ini` path.
- Current minimum acceptance remains standalone SS928 + GS1860/SS-LD-AS01 only:
  UDP 2368 receives 4873-byte / 40x30 packets, and a 30 cm obstruction makes most valid
  depth pixels `<1 m`.
- Next software comparison should align the SS928 MIPI path against the official dToF
  material, especially packet layout, GS1860 config, EEPROM/calibration, raw frame format,
  and `DtofProcess` input assumptions.

## 2026-06-03 open_camera standalone dToF route check

Scope remained standalone dToF only. No MCU bridge, CAN/serial actuator, motor, steering,
brake, throttle, or chassis control commands were started.

New route built from `vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof`
using the SS928 `aarch64-mix210-linux` toolchain and SDK libraries:

- Local build script updated: `tools/vm_build_open_camera_dtof_auto.sh`.
- Capture whitelist updated: `tools/capture_dtof_udp_pair.py` now permits
  `/opt/sample/open_camera_dtof_auto` and `sample_vio_dtof_auto`.
- First compatible build:
  `bd83286f1029a2ff1805b1af08e192d445214ce980cb5e1fe69370c3ae139873`,
  VM log `logs/vm_ssh_20260603_001453_7fa91f7c.log`.
- Corrected build with open_camera local `libsns_gs1860.a` linked before the SDK GS1860
  lib:
  `2ebac36070dc2dafef1b504208c2ded794f5df7a3faae70e6a8e62eba47c693c`,
  VM log `logs/vm_ssh_20260603_002009_f2fb5e31.log`.
- Deployed to board isolated directory `/opt/sample/open_camera_dtof_auto`:
  deployment log `logs/vm_ssh_20260603_002034_6dadf583.log`.

Runtime evidence:

- RGB/demo `sample_vio` in `/opt/sample/open_camera_dtof` is not useful for standalone
  dToF: it stops at the record-key prompt unless patched, and the patched keyauto run
  initializes IMX347/RGB and produces no dToF UDP.
- `open_camera_dtof_image/sample_vio` is not board-compatible: it requires newer
  GLIBC/GLIBCXX; `sample_vio_lib64` has an interpreter mismatch.
- `sample_vio_dtof_auto` first run entered `ROUTE1_DTOF_AUTO_START` but mixed SDK/local
  GS1860 libs caused register/EEPROM I2C failures and segfault:
  `logs/dtof_udp_pair_steady_open_camera_dtof_auto_j3_current_20260603_001722_board.log`.
- After correcting GS1860 link order, the I2C errors disappeared, but the board reported
  `ISP[2] already inited!` and segfaulted before UDP:
  `logs/dtof_udp_pair_steady_open_camera_dtof_auto_localgs_j3_current_20260603_002111_board.log`.
- Attempted media-stack reload:
  `.venv\Scripts\python tools\board_run.py --allow-risk "cd /opt/ko && ./load_ss928v100 -a"`.
  The helper timed out waiting for stdout. Subsequent SSH timed out, and serial COM11
  opened but only echoed the command without shell output:
  `logs/serial_20260603_002540_c6a3ce58.log`.

Current state:

- The open_camera dToF-only build is now viable enough to reach the dToF path without
  RGB key gating and without the earlier GS1860 I2C/register failure.
- The board currently needs physical recovery or operator confirmation before further
  tests; do not infer dToF failure from the post-reload board hang.
- Next after recovery: rerun a clean preflight, execute `init_dtof_cfg.sh`, then rerun
  the same steady capture:
  `.venv\Scripts\python tools\capture_dtof_udp_pair.py --condition steady_open_camera_dtof_auto_localgs_j3_recovered --board-cwd /opt/sample/open_camera_dtof_auto --binary sample_vio_dtof_auto --board-args 1 192.168.137.100 --seconds 45 --max-packets 180`.

2026-06-03 continuation recovery check:

- `ping -S 192.168.137.1 -n 2 192.168.137.100` succeeded, so the Windows wired
  interface and VM side of the 192.168.137.0/24 network are alive.
- `ping -S 192.168.137.1 -n 2 192.168.137.2` returned destination-host-unreachable
  from the Windows host; board IP is not reachable.
- `tools/board_serial.py --login-password "ebaina" --timeout 20 run "date; whoami; hostname"`
  opened COM11 but timed out waiting for the sentinel; the serial log only contains the
  echoed command:
  `logs/serial_20260603_003045_8b236f79.log`.
- Required next action remains physical board recovery/power-cycle before further dToF
  software tests.

2026-06-03 repeated recovery check:

- `ping -S 192.168.137.1 -n 2 192.168.137.100` still succeeded.
- `ping -S 192.168.137.1 -n 2 192.168.137.2` still returned destination-host-unreachable
  from the Windows host.
- `Test-NetConnection -ComputerName 192.168.137.2 -Port 22` failed.
- COM11 opened, but `tools/board_serial.py --login-password "ebaina" --timeout 20 run
 "date; whoami; hostname"` again timed out waiting for the sentinel; log:
  `logs/serial_20260603_003400_b170c1b1.log`.
- This confirms the same external blocker remains: no SSH path and no responsive serial
  shell. Further standalone dToF testing requires physical board recovery first.

## 2026-06-03 standalone dToF PWM laser-drive check

After the board was rebooted and recovered, the standalone dToF scope remained unchanged:
no OS08A20/case3/actuator work. Board-side SS928 official config was confirmed restored:

- `dtof.ini`:
  `7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6`
- `gs1860_register.ini`:
  `3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb`
- `dtof_init.sh`:
  `eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0`

Claude's hypothesis was that the GS1860 laser modulation PWM was never actually enabled.
The test was explicitly approved by the user because it can turn on the 940 nm dToF
emitter. Commands used the sysfs PWM interface only and did not touch any vehicle control
path.

Baseline before manual PWM:

- Board log copied to `logs/dtof_pwm_off_baseline_20260603_115919_board.log`.
- `sample_dtof_official_vi_chn_dtof3_dbg` produced the same short chn0/DtofProcess
  pattern as before: mostly `raw_nonzero=8220`, `out_eq_2=1170/1200`, `out_mid=2`,
  with occasional `raw_nonzero=10252`, `out_max=7579`.

Manual `pwmchip0/pwm0` test:

- Enable command:
  `CHIP=/sys/class/pwm/pwmchip0; if [ ! -d $CHIP/pwm0 ]; then echo 0 > $CHIP/export; sleep 0.2; fi; echo 0 > $CHIP/pwm0/enable 2>/dev/null || true; echo 8333 > $CHIP/pwm0/period; echo 6250 > $CHIP/pwm0/duty_cycle; echo normal > $CHIP/pwm0/polarity 2>/dev/null || true; echo 1 > $CHIP/pwm0/enable`
- Confirmed state: `period=8333`, `duty=6250`, `enable=1`, `polarity=normal`.
- The standard `run_dtof_phase1_condition.py` capture was not started because its
  preflight rejected the existing VM ROS bridge UDP listener:
  `logs/dtof_phase1_pwm0_on_vi_chn_dtof3_j4_20260603_120156_preflight_stdout.log`.
- Manual board/ROS captures were used instead:
  - `logs/dtof_pwm_on_manual_20260603_120231_board.log`
  - `logs/dtof_pwm_on_manual_20260603_120231_vm_coherence.log`
- Result: no improvement. ROS coherence remained `valid_coverage/1200: min=30
  median=30 max=41`, centre 8x8 had no valid returns. Board output stayed at the same
  sentinel-heavy pattern, typically `out_eq_2=1170/1200`.

Manual `pwmchip0/pwm5` test:

- Rationale: `dtof_init.sh` pinmuxes both `pwm0_0` and `pwm0_5`, so the second candidate
  was also checked.
- Enable command was the same as above with `pwm5`.
- Confirmed state: `period=8333`, `duty=6250`, `enable=1`, `polarity=normal`.
- Captures:
  - `logs/dtof_pwm5_on_manual_20260603_120349_board.log`
  - `logs/dtof_pwm5_on_manual_20260603_120349_vm_coherence.log`
- Result: no improvement. ROS coherence again remained `valid_coverage/1200: min=30
  median=30 max=41`, centre 8x8 had no valid returns. Board output again stayed at the
  same `out_eq_2=1170/1200` sentinel-heavy pattern.

Cleanup:

- Both tested PWM channels were disabled after capture.
- Final saved state: `logs/dtof_pwm_final_state_20260603_1204.log`
  (`pwm0=0`, `pwm5=0`).

Conclusion:

- The narrow software hypothesis "only pwm0_0 or pwm0_5 sysfs enable is missing" is not
  sufficient. Both channels can be enabled, but neither makes the standalone dToF output
  scene-responsive.
- This does not prove that the optical transmitter hardware is good; it only shows that
  manually enabling these two PWM candidates did not change the observed depth/coverage.
- Continue the standalone dToF software path from the stronger existing evidence:
  official UDP framing is alive, but the SS928 VI/raw/DtofProcess path still produces
  invariant/sentinel-heavy output. The next software focus remains raw format/LINE
  compression, MIPI/VI mapping, and the exact `DtofProcess` input assumptions.

## 2026-06-03 VI chn0 probe without pipe dump-attr switch

The earlier official path showed a hard failure after `dtof_dumpraw.c` changed the VI
pipe from RAW12/LINE to RAW10/NONE: raw became zero after the first frames. To test
whether VI chn0 could provide a usable outlet without changing the pipe dump attr, a
fresh official-SDK diagnostic binary was built and deployed:

- Build script: `tools/vm_build_official_vi_chn_probe.sh`.
- VM build log: `logs/vm_ssh_20260603_120712_e5e9a03f.log`.
- Binary:
  `/home/ebaina/official_dtof_vi_chn_probe_20260603_120707/src/dtof/sample_dtof_official_vi_chn_probe_dbg`
- sha256:
  `861bec9379da5cc991667bd68b157fa514be5c4c9577fccd9b7bb25d8968ee48`
- Deployed board file:
  `/opt/sample/official_dtof/sample_dtof_official_vi_chn_probe_dbg`
- Deployment log: `logs/vm_ssh_20260603_120738_ff92086d.log`.
- Run command/logs:
  - `logs/dtof_vi_chn_probe_j4_20260603_120756_commands.txt`
  - `logs/dtof_vi_chn_probe_j4_20260603_120756_board.log`

Key runtime evidence:

- Config-time chn0 attr before adjustment reported `pixfmt=28 compress=0 depth=0`.
- After setting depth to 2 and re-enabling chn0, the attr still reported
  `pixfmt=28 compress=0 depth=2`.
- But the actual frames returned by `ss_mpi_vi_get_chn_frame(vi_pipe=1, chn=0)` were:
  `w=2560 h=31 stride0=3552 pixfmt=21 compress=4`.
- The first bytes were stable LINE-compressed-looking data, for example row1:
  `16 00 00 fd 3f a0 ff 0f 82 20 08 82 10 22 92 fa`.
- `ss_mpi_vi_release_chn_frame` returned `0xa0108007`, matching the earlier evidence
  that these frames are not normal chn frames for the release path.

Conclusion:

- VI chn0 does not provide a useful uncompressed linear raw outlet for GS1860 on this
  path. The actual frame still arrives as RAW12/LINE (`pixfmt=21 compress=4`), even when
  the chn attr says YUV/none.
- Therefore the next software target is not "read chn0 instead of pipe"; it is either:
  decode/handle SS928 LINE-compressed RAW12 correctly before `DtofProcess`, or find the
  official VI/pipe configuration that makes GS1860 output linear raw without going to
  zero.

## 2026-06-03 controlled 20-30 cm occlusion first-run check

The user placed a flat obstruction roughly 20-30 cm in front of the standalone dToF
module. The board was rebooted so that `sample_dtof_official_vi_chn_dtof3_dbg` would run
as the first dToF sample after a clean boot. The VM dToF ROS bridge was temporarily
stopped to free UDP 2368 for the strict UDP checker.

Reboot/config evidence:

- Board came back over SSH and official config hashes were confirmed:
  - `dtof.ini`:
    `7bbf91218b669893394f90d51c6435858101fab63cd5d4d82fd688732aabdeb6`
  - `gs1860_register.ini`:
    `3546a82d5e58bda430c69c2ff3a40dd0e73bf5fa65f697cbe0a902d4b35708bb`
  - `dtof_init.sh`:
    `eb7209cb7eceb8c67d9eacf675e2609042d66d8612d5aafce2e2cf12473df9a0`
- Preflight passed before capture; the only warning was the existing Foxglove TCP 8765
  listener.

Capture command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition near30cm_occlusion_first_run_j4 --binary sample_dtof_official_vi_chn_dtof3_dbg --case 2 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_commands.txt
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_preflight.json
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_preflight_summary.txt
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_preflight_stdout.log
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_board.log
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_vm.log
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_report.json
logs/dtof_phase1_near30cm_occlusion_first_run_j4_20260603_121356_report.report_stdout.log
```

UDP format result:

```text
PACKETS=300
GOOD_SIZE_4873=300
GOOD_HEADER_40x30=300
GOOD_PIXEL_NUMBER_1200=300
GOOD_START_PIXEL_0=300
GOOD_FRAME_RATE_30=300
DTOF_UDP_CHECK=PASS
DTOF_UDP_STRICT_CHECK=PASS
ALL_2MM_PACKETS=0
VALID_NON_SENTINEL_PACKETS=300
```

Near-depth result:

```text
NEAR_ANY_LT_1000_PACKETS=300
NEAR_MAJORITY_LT_1000_PACKETS=0
NEAR_MEDIAN_LT_1000_PACKETS=0
depth_valid.median ~= 340 valid pixels/packet
depth_valid_median.median ~= 5593 mm
depth_valid_lt1000.median ~= 20 pixels/packet
```

Representative packet summaries:

```text
valid=343 valid_median=5683.0 valid_lt1000=16 center=2
valid=334 valid_median=5479.5 valid_lt1000=16 center=0
valid=350 valid_median=5458.0 valid_lt1000=29 center=2
```

Board-side first-run state:

```text
raw_nonzero.median=76521
raw_max.median=1023
out_eq_2.median=519/1200
out_max.median=8058
```

Conclusion:

- The stable standalone UDP framing requirement is met in this run.
- The 20-30 cm occlusion acceptance criterion is not met: the run still reports a far
  scene, with only a small minority of valid pixels below 1 m.
- Because the test was first-run-after-reboot and had valid non-sentinel depth, the
  failure is not the old all-2mm or raw-zero failure. Either the physical obstruction did
  not cover the active dToF field of view, or the current chn0/DtofProcess output remains
  spatially mis-registered/biased enough that a near obstruction is not dominating the
  valid depth set.
- Next controlled test should reposition the object closer and more centrally over the
  actual dToF optical window, or fully cover the dToF window while capturing the first
  run after reboot. Use the same command and require
  `NEAR_MAJORITY_LT_1000_PACKETS > 0` (ideally most packets) before declaring acceptance.

## 2026-06-03 seller Euler Pi 2.0 dToF package comparison and J4 retest

The user downloaded the seller-provided Euler Pi 2.0 files from the Baidu share into
`vendor/`. Two newly added zip files were inspected:

- `vendor/01.Sensor+3D dToF画中画源码.zip`
- `vendor/02.Sensor+3D dToF画中画可执行程序.zip`

The source package is essentially the same dToF sample baseline as the existing official
MPP sample for the non-PIP dToF path. Its `dtof_init.sh`, `dtof.ini`, and
`gs1860_register.ini` match the existing official files.

The executable package is different and turned out to be important. Its
`gs1860_register.ini` uses a different GS1860/PWM configuration:

```text
source/official pwmCommon:
0x20=0x12A1; PWM0_OUT0_0_P
0x42=0x0682
0x62=0x04E2 or 0x0589
0x82=0x0005

seller executable pwmCommon:
0x1B=0x12A4; PWM1_OUT14_0_P
0x3D=0x0682
0x5D=0x05B4; 1667 * 86% = 1433, 7.6V
0x7D=0x0005
```

The seller executable `dtof.ini` also enables/tunes near-far mode switching differently
from the source/official config, including lower thresholds and 20000 shot count:

```text
baseThRatio=5.0
peakThRatio=6.0
configSwitchFlag=true
totalShotNumNear=20000
totalShotNumFar=20000
distThreshold=1500.0
```

This explains why the earlier manual PWM tests on `pwmchip0/pwm0` and `pwmchip0/pwm5`
were inconclusive: the seller runtime configuration points at `PWM1_OUT14_0_P`, not the
two sysfs PWM candidates that were tested.

The seller executable package was deployed without overwriting the official directory:

```text
board dir: /opt/sample/seller_dtof
sample_dtof sha256: e174f07136ccbf982d2ecb3112bc59b1a558a3cd79da6a40f4a22fa6811bbd50
dtof_init.sh sha256: 243c289d5b06d569c6b8fc7a19cf448fb1441322c366832abf0dca4bbd249af3
dtof.ini sha256: b2a8f8ae4d9a9b907cecc29b38b1d711c4e936e330bd29f5d3bdfca36f50f45e
gs1860_register.ini sha256: 10fb0ee852380a151ee727ca5970b1103dbfee173685462eee8e6c52e440395f
```

The first upload attempt used parallel fallback uploads and corrupted files because
`tools/board_sftp_put.py` uses a shared `/tmp/_upload_b64.tmp` fallback path. All files
were then re-uploaded sequentially and verified by sha256 before anything was run.

### Seller executable package, J4/case2, near/full cover

Command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_bin_near_fullcover_j4_case2 --board-dir /opt/sample/seller_dtof --binary sample_dtof --case 2 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_seller_bin_near_fullcover_j4_case2_20260603_132226_commands.txt
logs/dtof_phase1_seller_bin_near_fullcover_j4_case2_20260603_132226_board.log
logs/dtof_phase1_seller_bin_near_fullcover_j4_case2_20260603_132226_vm.log
logs/dtof_phase1_seller_bin_near_fullcover_j4_case2_20260603_132226_report.json
```

Result:

```text
PACKETS=300
GOOD_SIZE_4873=300
GOOD_HEADER_40x30=300
GOOD_PIXEL_NUMBER_1200=300
DTOF_UDP_STRICT_CHECK=PASS
VALIDISH_DEPTH_PACKETS=2
ALL_2MM_PACKETS=298
NEAR_MEDIAN_LT_1000_PACKETS=2
```

The seller executable produced two initial near packets around 166 mm, then became all
2 mm sentinel. Because this binary has no internal debug prints, a hybrid debug run was
needed.

### Seller executable package, J3/case1 check

Command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_bin_near_fullcover_j3_case1 --board-dir /opt/sample/seller_dtof --binary sample_dtof --case 1 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_seller_bin_near_fullcover_j3_case1_20260603_132326_board.log
logs/dtof_phase1_seller_bin_near_fullcover_j3_case1_20260603_132326_vm.log
logs/dtof_phase1_seller_bin_near_fullcover_j3_case1_20260603_132326_report.json
```

Result:

```text
gs1860_write_register: I2C_WRITE error
gs1860_read_eeprom: CMD_I2C_READ error
DTOF_PHASE1_RC=255
PACKETS=0
DTOF_UDP_STRICT_CHECK=FAIL
```

Conclusion: the connected dToF is on the J4/case2 path, not J3/case1.

### Seller runtime config + official debug binary, J4/case2

A clean hybrid directory was created:

```text
/opt/sample/seller_debug
```

It contains the official debug binary
`sample_dtof_official_vi_chn_dtof3_dbg`, plus the seller executable package's
`dtof_init.sh`, `dtof.ini`, and `gs1860_register.ini`.

Command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_cfg_debug_near_fullcover_j4_case2 --board-dir /opt/sample/seller_debug --binary sample_dtof_official_vi_chn_dtof3_dbg --case 2 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_seller_cfg_debug_near_fullcover_j4_case2_20260603_132455_board.log
logs/dtof_phase1_seller_cfg_debug_near_fullcover_j4_case2_20260603_132455_vm.log
logs/dtof_phase1_seller_cfg_debug_near_fullcover_j4_case2_20260603_132455_report.json
```

Result:

```text
PACKETS=300
GOOD_SIZE_4873=300
GOOD_HEADER_40x30=300
GOOD_PIXEL_NUMBER_1200=300
DTOF_UDP_STRICT_CHECK=PASS
VALID_NON_SENTINEL_PACKETS=300
ALL_2MM_PACKETS=0
NEAR_ANY_LT_1000_PACKETS=300
NEAR_MAJORITY_LT_1000_PACKETS=300
NEAR_MEDIAN_LT_1000_PACKETS=300
depth_valid.median=30
depth_valid_median.median=166 mm
```

Board-side debug was stable:

```text
raw_nonzero=8220
raw_max=1023
out_max=187
out_eq_2=1170/1200
out_mid=2
```

This is the first stable run where the standalone dToF official UDP stream reports near
depth under the user's near/full-cover condition. However, only 30 of 1200 pixels are
non-2mm in each packet.

### Valid-point layout diagnostic

`tools/vm_dtof_udp_check.py` was extended to print the first packet's non-2mm valid
point layout (`FIRST_VALID_ROW_COUNTS`, `FIRST_VALID_COL_COUNTS_TOP`,
`FIRST_VALID_COORDS`).

Command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_cfg_debug_layout_near_fullcover_j4_case2 --board-dir /opt/sample/seller_debug --binary sample_dtof_official_vi_chn_dtof3_dbg --case 2 --seconds 20 --max-packets 120
```

Artifacts:

```text
logs/dtof_phase1_seller_cfg_debug_layout_near_fullcover_j4_case2_20260603_132649_board.log
logs/dtof_phase1_seller_cfg_debug_layout_near_fullcover_j4_case2_20260603_132649_vm.log
logs/dtof_phase1_seller_cfg_debug_layout_near_fullcover_j4_case2_20260603_132649_report.json
```

Result:

```text
PACKETS=120
GOOD_SIZE_4873=120
GOOD_HEADER_40x30=120
GOOD_PIXEL_NUMBER_1200=120
DTOF_UDP_STRICT_CHECK=PASS
VALID_NON_SENTINEL_PACKETS=120
NEAR_MEDIAN_LT_1000_PACKETS=120
FIRST_VALID_COORD_COUNT=30
FIRST_VALID_ROW_COUNTS=0:1,1:1,2:1,3:1,4:1,5:1,6:1,7:1,8:1,9:1,10:1,11:1,12:1,13:1,14:1,15:1,16:1,17:1,18:1,19:1,20:1,21:1,22:1,23:1,24:1,25:1,26:1,27:1,28:1,29:1
FIRST_VALID_COL_COUNTS_TOP=4:30
FIRST_VALID_COORDS=0:4:187;1:4:185;2:4:184;...;29:4:138
```

Conclusion:

- The seller executable runtime config is a real breakthrough for the standalone dToF:
  it changes the system from far-depth/5 m or all-2mm behavior to stable near returns
  under the near/full-cover condition.
- The connected hardware path is J4/case2.
- The remaining software issue is spatial/data layout quality: only one output column
  (`col=4`, 30 pixels) is non-2mm, while the rest of the 40x30 grid remains sentinel.
  That strongly suggests a VI LINE/raw unpacking, DtofProcess input layout, or output
  mapping issue remains.
- Do not revert to the source/official `gs1860_register.ini`; the seller executable
  `gs1860_register.ini` is the only tested config that gives stable near depth.

### Seller runtime config first-run after board reboot

Because earlier notes showed that the `sample_dtof_official_vi_chn_dtof3_dbg` path can
fall into a fixed `col=4` degraded state after repeated runs on the same boot, the board
was rebooted and the seller-runtime-config hybrid was run immediately as the first dToF
sample after boot.

Reboot command:

```powershell
.venv\Scripts\python tools\board_run.py --allow-risk "sync; reboot"
```

Board SSH returned at:

```text
Wed Jun  3 09:39:16 UTC 2026
up 0 min
```

First-run capture command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_cfg_debug_first_run_after_reboot_near_fullcover_j4_case2 --board-dir /opt/sample/seller_debug --binary sample_dtof_official_vi_chn_dtof3_dbg --case 2 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_seller_cfg_debug_first_run_after_reboot_near_fullcover_j4_case2_20260603_133032_board.log
logs/dtof_phase1_seller_cfg_debug_first_run_after_reboot_near_fullcover_j4_case2_20260603_133032_vm.log
logs/dtof_phase1_seller_cfg_debug_first_run_after_reboot_near_fullcover_j4_case2_20260603_133032_report.json
```

Result:

```text
PACKETS=300
GOOD_SIZE_4873=300
GOOD_HEADER_40x30=300
GOOD_PIXEL_NUMBER_1200=300
DTOF_UDP_STRICT_CHECK=PASS
VALID_NON_SENTINEL_PACKETS=300
ALL_2MM_PACKETS=0
NEAR_ANY_LT_1000_PACKETS=300
NEAR_MAJORITY_LT_1000_PACKETS=0
NEAR_MEDIAN_LT_1000_PACKETS=0
depth_valid.median ~= 422.5 pixels/packet
depth_valid_median.median ~= 6077.5 mm
depth_valid_lt1000.median ~= 8 pixels/packet
```

Board-side debug:

```text
raw_nonzero ~= 76510-76525
raw_max=1023
out_eq_2 ~= 469-541/1200
out_max ~= 8054-8150
```

First-packet layout:

```text
FIRST_VALID_COORD_COUNT=421
FIRST_VALID_ROW_COUNTS=distributed across all rows
FIRST_VALID_COL_COUNTS_TOP=distributed across many columns
```

Conclusion:

- The post-reboot first-run is the full-FOV "good state", not the fixed `col=4` degraded
  artifact.
- Under the current physical near/full-cover setup, the first-run good state still
  reports a far scene with median valid depth around 6 m; it does not satisfy the
  `<30 cm obstruction -> majority valid depth <1 m` acceptance criterion.
- The previous stable 166 mm output was the known column-4 degraded state and must not be
  counted as acceptance.
- The seller runtime config remains useful because it fixes the PWM/register direction,
  but final acceptance still requires either a true physical cover over the active dToF
  optical window or further GS1860/VI/raw layout work that makes the full-FOV first-run
  respond to near occlusion.

### Seller native executable first-run after board reboot

To exclude the possibility that the far first-run was caused by the hybrid debug binary,
the board was rebooted again and the seller native executable was run immediately as the
first dToF sample after boot.

Capture command:

```powershell
.venv\Scripts\python tools\run_dtof_phase1_condition.py --condition seller_bin_first_run_after_reboot_near_fullcover_j4_case2 --board-dir /opt/sample/seller_dtof --binary sample_dtof --case 2 --seconds 35 --max-packets 300
```

Artifacts:

```text
logs/dtof_phase1_seller_bin_first_run_after_reboot_near_fullcover_j4_case2_20260603_134834_board.log
logs/dtof_phase1_seller_bin_first_run_after_reboot_near_fullcover_j4_case2_20260603_134834_vm.log
logs/dtof_phase1_seller_bin_first_run_after_reboot_near_fullcover_j4_case2_20260603_134834_report.json
```

Result:

```text
PACKETS=300
GOOD_SIZE_4873=300
GOOD_HEADER_40x30=300
GOOD_PIXEL_NUMBER_1200=300
DTOF_UDP_STRICT_CHECK=PASS
VALIDISH_DEPTH_PACKETS=2
ALL_2MM_PACKETS=298
VALID_NON_SENTINEL_PACKETS=2
NEAR_MAJORITY_LT_1000_PACKETS=0
NEAR_MEDIAN_LT_1000_PACKETS=0
```

The first two packets were full-FOV far-depth packets:

```text
seq=1 valid=408 valid_median=6005.5 valid_lt1000=9
seq=2 valid=382 valid_median=6022.0 valid_lt1000=8
```

Then the seller native executable collapsed to all-2mm for the remaining 298 packets.

Conclusion:

- The seller native executable still uses the old pipe dump path and is not a viable
  steady-state board binary, even though its runtime configs are useful.
- The current viable software candidate remains:
  `/opt/sample/seller_debug/sample_dtof_official_vi_chn_dtof3_dbg`, i.e. VI chn0 read
  with pipe-release plus the seller executable package's `dtof.ini` and
  `gs1860_register.ini`.
- This confirms the remaining acceptance blocker is not the hybrid debug binary alone:
  the true full-FOV first-run depth under the current physical setup is still far
  (~6 m median valid depth), not near.
