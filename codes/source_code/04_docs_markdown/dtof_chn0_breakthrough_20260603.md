# dToF BREAKTHROUGH — steady-state valid depth via VI chn0 + pipe-release

Date: 2026-06-03
Scope: perception-only. No MCU bridge / CAN / serial actuator / motor / steering /
brake / throttle was ever started. Car cannot move.

## TL;DR

The long-standing "all 2 mm after frame 2 / `pipe_attr_zero_after_switch`" wall is
**BROKEN**. Standalone single dToF (GS1860, case2/J4, sensor3/dev3/pipe1) now produces
**continuous, live, valid depth** over UDP 2368 (4873-byte / 40×30 / 1200-pixel), with
**no leak, no stall, clean exit**, sustained ≥ 700 packets over 60 s at ~11.6 Hz.

## Root cause of the old failure (confirmed)

`dtof_dumpraw.c::vi_bayerdump()` used the VI **pipe raw-dump** path:
`get_dump_pipe` → `set_dump_pipe_attr()` (forces the pipe to `RAW10 + NONE`) →
`dump_process` reads `ss_mpi_vi_get_pipe_frame`.

On this GS1860 path the pipe natively delivers `RAW12 + LINE` (pixfmt 21, compress 4,
stride 3552). Forcing it to `RAW10 + NONE` (pixfmt 20, compress 0, stride 3200) makes the
front-end deliver **empty buffers** (`raw_nonzero=0`) from frame 3 on, so `DtofProcess`
emits the 2 mm "no valid peak" sentinel for all 1200 pixels. The only populated frames the
old path ever saw were the 1–2 `RAW12 + LINE` buffers flushed during the attribute
transition. RAW10+NONE-at-creation also gives zero; keepattr (RAW12+LINE held) delivers
bytes via the pipe path but `deal_frame_data` reads them as the partially-populated
compressed layout → mostly 2 mm.

## The fix

Bypass the broken raw-dump entirely and read the **VI channel 0** output of the same
`BYPASS_BE` pipe, then feed the existing `deal_frame_data → DtofProcess → UdpSendTofData`
chain unchanged.

Two non-obvious points that made it work:

1. **chn0 must be given a user queue depth.** The dtof sample starts chn0
   (`chn_need_start = TD_TRUE`) but with `chn_attr.depth = 0`, so `get_chn_frame` returns
   nothing usable. Set `vi_cfg->pipe_info[0].chn_info[0].chn_attr.depth = 4` at config time
   (only `depth`; setting the chn `pixel_format` to RAW12 is rejected with `0xa0108007`).
   A runtime `disable_chn / set_chn_attr(depth) / enable_chn` works too.

2. **Release the frame via the PIPE API, not the CHN API.** For this `BYPASS_BE`
   passthrough chn, `ss_mpi_vi_release_chn_frame()` returns `0xa0108007`
   (`OT_ERR_VI_ILLEGAL_PARAM`) and leaks exactly one VB block per frame (it stalls at the
   VB pool size — measured: exactly 23 frames = 15+8 pool blocks). `ss_mpi_vi_release_pipe_frame(vi_pipe, &frame)`
   returns `0x0` and recycles cleanly → steady-state, and VB is empty after exit.

`get_chn_frame` returns frames with **advancing `time_ref`/`pts`** (e.g. time_ref
6,8,10,12… ; pts +~54.6 ms ≈ 18 Hz) → the frames are genuinely live, not a frozen buffer.

## Evidence (this session, board reboots between runs for clean VB)

Build scripts (local, idempotent SDK-zip patchers):
- `tools/vm_build_official_vi_chn_probe.sh` — read-only chn0 probe (proved chn0 delivers
  non-zero live RAW12 frames).
- `tools/vm_build_official_vi_chn_dtof.sh` — v1: chn0 → DtofProcess, chn-release (leaks).
- `tools/vm_build_official_vi_chn_dtof2.sh` — v2: + pipe-release fallback (no leak).
- `tools/vm_build_official_vi_chn_dtof3.sh` — v3: config-time chn depth + matched
  read/pipe-release + pts logging. **Production candidate.**

Board binary (case2/J4): `/opt/sample/official_dtof/sample_dtof_official_vi_chn_dtof3_dbg`
(VM build sha256 `97cb3af0…` for v2 source; v3 rebuilt under
`/home/ebaina/official_dtof_vi_chn_dtof3_*`).

Key runs:
- `logs/dtof_phase1_vi_chn_dtof2b_j4_20260603_015438_*` — 300 pkts, ALL_2MM=0, clean exit.
- `logs/dtof_phase1_vi_chn_dtof3_j4_20260603_*` — config-depth, pts advancing, 250 pkts.
- `logs/dtof_phase1_vi_chn_dtof3_60s_j4_20260603_020639_*` — **700 pkts / 60 s**, ALL_2MM=0,
  full-FOV far state: per-packet `valid≈331–359`, `valid_median≈5.4–5.8 m`, varying
  (live), center pixel resolves (e.g. 7893 mm).
- `logs/dtof_phase1_vi_chn_v1_recompare_j4_20260603_*` — same scene, frames 1–8 show the
  concentrated near state (raw_nonzero 8220, ~30 valid @ ~16 cm), frames 9–12 the full
  far state (raw_nonzero ~76520, ~355 valid @ ~5–8 m): the histogram state is
  **sensor/time driven**, not release-method driven. Both are valid live data; neither is
  the old 2 mm collapse.

## Acceptance status

- [x] Single dToF stably outputs UDP 2368 / 4873-byte / 40×30 / 1200-pixel — **DONE**
      (700 pkts/60 s, ALL_2MM=0, clean exit, no leak, ~11.6 Hz).
- [ ] Under a < 30 cm flat occlusion, most valid depths < 1 m — needs a **controlled
      physical A/B** (clear vs object at ~30 cm). The path already shows the sensor sees
      both near (~16 cm, concentrated histogram) and far (~5.5 m, full histogram) states
      live; a controlled occlusion confirms responsiveness and finalizes this item.
- [x] Every result has a saved log + reproducible command.

## Reproduce

```powershell
$env:PYTHONIOENCODING='utf-8'
# (board reboot first if VB is dirty: board_run.py --allow-risk "sync; reboot")
.venv\Scripts\python tools\run_dtof_phase1_condition.py `
  --condition vi_chn_dtof3_j4 --binary sample_dtof_official_vi_chn_dtof3_dbg `
  --case 2 --seconds 30 --max-packets 300
# Expect: PACKETS>0, ALL_2MM_PACKETS=0, VALID_NON_SENTINEL_PACKETS=PACKETS, clean exit.
```

## Depth-quality characterization (spatial probe, `tools/vm_dtof_spatial_probe.py`)

The chn0 stream alternates between two frame states (raw_nonzero ≈ 76500 "good" vs ≈ 8220
"degraded"). Spatial decode of the UDP depth grid (40×30) shows:

- **GOOD state** (first run after a clean reboot): `valid ≈ 321–363` pixels/packet, real
  full-FOV depth with scene structure — scattered returns from ~167 mm to several metres,
  137/1200 pixels ever < 1 m, distributed across the frame. This is genuine depth.
- **DEGRADED state** (any rerun on the same boot, no reboot): only ~30 valid pixels, and
  they are a **fixed artifact in output column 4** (a smooth linear ramp ~57→101 mm down
  the 30 rows) plus all-2 mm everywhere else. Not a real object.

**Operational rule (confirmed 3/3 reboots):** the GS1860 yields good full-histogram frames
on the **first `dtof_init` + run after a clean reboot**, and that good state is sustained
for the whole run (verified 700 pkts / 60 s). Re-running the sample on the same boot
(without a power-cycle/reset of the sensor) drops it into the degraded column-4 state.
→ For the realistic deployment (dToF started once by `S90autorun` on boot, ROS consumes the
UDP), the stream is in the GOOD state. For repeated manual test runs, reboot first.
The inter-run reset (why a second `dtof_init` does not restore the good state without a
reboot) is an open follow-up; likely a GS1860 / VI-FE state that GPIO96 reset alone does
not fully clear.

Column 4 also carries a small persistent bias even in the good state (~440 mm), i.e. it is
a decode artifact, not a physical object (its depth changes with frame state).

Criterion 2 ("most valid depths < 1 m under < 30 cm occlusion") is still open: the current
scene resolves a far room (~5.5 m) with only scattered < 1 m returns, so a controlled A/B
(flat board filling the FOV at ~30 cm vs cleared) is needed to confirm the sensor drives
most pixels < 1 m on occlusion.

## ROS2 + Foxglove live point cloud (2026-06-03)

Standalone single-dToF (no camera) → ROS2 → Foxglove pipeline, all perception-only:

- Board: `sample_dtof_official_vi_chn_dtof3_dbg 2 192.168.137.100` started detached as the
  **first run after reboot** (good state), via
  `setsid sh -c 'sleep 36000 | ./sample_dtof_official_vi_chn_dtof3_dbg 2 192.168.137.100 ...' &`.
- VM bridge: `tools/vm_dtof_ros_bridge.py` (pushed to `/tmp/`, run with
  `source /opt/ros/humble/setup.bash; python3 /tmp/vm_dtof_ros_bridge.py`). Publishes
  `/dtof/points` (PointCloud2), `/dtof/depth` (Image 32FC1), `/dtof/info`. Uses FOV-derived
  intrinsics (fx≈34.6, fy≈35.3, cx=19.5, cy=14.5) because the packet EEPROM calib is
  degenerate (fy=1, cx=cy=0); filters the 2 mm sentinel to NaN.
- Foxglove: `tools/vm_foxglove_restart_with_dtof.sh` relaunches the VM foxglove_bridge on
  8765 with `/dtof/points`,`/dtof/depth`,`/dtof/info` added to the topic whitelist (keeps
  the `/parking/*` ones). Connect Foxglove Studio to **ws://192.168.247.129:8765** (or
  ws://192.168.137.100:8765); 3D panel → `/dtof/points`, Image panel → `/dtof/depth`.
- Verified: `/dtof/points` @ **18.3 Hz**, ~333 valid pixels/packet, depth ~0.09–8.0 m,
  live (varies with scene).

Note: this relies on the board sample being a fresh first-run-after-reboot (good state).
Re-running the board sample without reboot degrades to the column-4 artifact (see above).

## Notes / next

- Operational caveat: any chn-release-leaking binary (v1, the read-only probe) leaves the
  VB pool allocated; reboot to clear before the next run. v2/v3 (pipe-release) exit clean.
- Near-field quality / coverage and any `dtof.ini` near/far (`configSwitchFlag`) tuning are
  a separate Phase-2 step, to be done only after the controlled occlusion A/B.
- ROS2 `/dtof/*` bridge can now consume this stream (it already worked off the 4873-byte
  UDP); wiring it is the next perception step once occlusion is validated.
