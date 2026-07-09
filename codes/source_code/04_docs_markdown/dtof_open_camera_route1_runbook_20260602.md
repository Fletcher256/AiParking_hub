# open_camera dtof-only route1 runbook - 2026-06-02

Scope: perception-only backup route for Euler Pi / SS928 + GS1860 on the current J3
physical connection (`dtof0`, `sensor2`, `i2c4`). This runbook does not authorize
execution. Every state-changing VM/board command still requires explicit approval.

## Why this route exists

The primary route remains `sample_dtof` clean RAW10/NONE-at-creation. If that route fails
or stays blocked, open_camera is the next useful software topology because it uses the
HiEuler `sample_vio` dToF path rather than the MPP `sample_dtof` case1 pipe mapping.

Local and VM read-only checks show:

- `sample_vio` is already dtof-only in source: `SUPPORT_RGB 0`, `SUPPORT_DTOF 1`.
- For the current J3/dtof0 physical target, the runtime argument is expected to be:
  `./sample_vio 1 192.168.137.100`.
- `sns_info[1].i2c_bus = 5`; the dToF code subtracts one and selects the J3/i2c4 branch.
- That branch uses `vi_dev=2`, `vi_pipe=2`, `mipi_dev=2`, lane `4`, which differs from
  MPP `sample_dtof` case1 pipe 1.

## Current VM artifacts

Read-only VM evidence:

```text
logs/vm_ssh_20260602_195518_ad58932b.log
logs/vm_ssh_20260602_195518_455f27cb.log
logs/vm_ssh_20260602_195518_9f81066c.log
logs/vm_ssh_20260602_195551_e346bde5.log
logs/vm_ssh_20260602_195551_fe6bebb6.log
logs/vm_ssh_20260602_195551_f629a2dc.log
logs/vm_ssh_20260602_195551_49945e88.log
```

VM files:

```text
/home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/sample_vio
/home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/dtof.ini
/home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/gs1860_register.ini
/home/ebaina/Workspace/open_camera-master/dToF/scripts/init_dtof_cfg.sh
/home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c
/home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/dtof_dumpraw.c
```

Observed VM SHA256:

```text
b39d168757f2b0832b5bfa74b6820648af8e2c47973134adb0c6847e4ee5a0a5  demo/sample_vio
b2a8f8ae4d9a9b907cecc29b38b1d711c4e936e330bd29f5d3bdfca36f50f45e  demo/dtof.ini
10fb0ee852380a151ee727ca5970b1103dbfee173685462eee8e6c52e440395f  demo/gs1860_register.ini
ecbe1b168e1ec509922419a3112a2aae3ffc9339dad9cf77061be109428cd8d5  code/mipi_imx347/imx347.c
13c00d1c4da7b8b5ed6aa5df6977f7ff08ba8324067152113c46cc0beae80694  code/mipi_imx347/dtof_dumpraw.c
```

## Current board state

Read-only board checks were run through `tools/board_run.py`; this wrapper printed output
directly and did not create separate log files for these commands.

```text
ls -ld /opt/sample /opt/sample/official_dtof /opt/sample/open_camera_dtof /root/open_camera_dtof 2>/dev/null || true
find /opt/sample /root -maxdepth 3 -type f -name sample_vio -o -name dtof.ini -o -name gs1860_register.ini 2>/dev/null | sort | head -80
ps -ef | grep -i -e sample_vio -e sample_dtof | grep -v grep || true
```

Observed:

- `/opt/sample/open_camera_dtof` does not exist.
- Existing `sample_vio` binaries are under `/opt/sample/mipi_rx/*` and are not the
  open_camera dToF demo.
- No `sample_vio` or `sample_dtof` process was running in the read-only check.
- One attempted process check containing forbidden actuator names was blocked locally by
  `board_run.py`; it was not sent to the board.

## Step A - Deploy route1 files to a separate board directory

Requires approval because it creates a board directory and writes files under
`/opt/sample/open_camera_dtof`. Do not overwrite `/opt/sample/official_dtof/sample_dtof`.

```powershell
.venv\Scripts\python tools\vm_ssh_run.py --timeout 120 --allow-risk run "sshpass -p ebaina ssh -o StrictHostKeyChecking=no root@192.168.137.2 'mkdir -p /opt/sample/open_camera_dtof' && sshpass -p ebaina scp -p -o StrictHostKeyChecking=no /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/sample_vio /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/dtof.ini /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/demo/gs1860_register.ini /home/ebaina/Workspace/open_camera-master/dToF/scripts/init_dtof_cfg.sh root@192.168.137.2:/opt/sample/open_camera_dtof/"
```

Purpose: deploy only the open_camera dToF demo binary, its two config files, and the
open_camera dToF init script into an isolated directory.

Risk: creates one board directory and writes four board files. It does not start dToF or
any actuator path. The command uses `--allow-risk` only after explicit approval because it
contains `mkdir`.

Read-only verification after deployment:

```powershell
.venv\Scripts\python tools\board_run.py "cd /opt/sample/open_camera_dtof && sha256sum sample_vio dtof.ini gs1860_register.ini init_dtof_cfg.sh && ls -l"
```

## Step B - open_camera dToF init

Requires separate approval because it writes a board register through `bspmm` and toggles
GPIO96 reset via `/sys/class/gpio`.

```powershell
.venv\Scripts\python tools\board_run.py --allow-risk "cd /opt/sample/open_camera_dtof && ./init_dtof_cfg.sh"
```

Purpose: apply the open_camera dToF reset/pin setup expected by its README before running
`sample_vio`.

Risk: changes board sensor/reset GPIO state and register mux state. It does not start any
MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or chassis
control path.

## Step C - J3/case route1 steady capture

Requires separate approval because it starts the board dToF perception sample and VM UDP
listener. No physical near-object action is needed for the first steady gate.

Use the generic paired UDP capture helper. It only accepts whitelisted board sample names
and whitelisted board directories; it does not support arbitrary board commands.

Read-only preflight-only validation has already passed:

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

The validation did not start VM UDP capture or the board sample.

```powershell
.venv\Scripts\python tools\capture_dtof_udp_pair.py --condition steady_open_camera_dtof_j3 --board-cwd /opt/sample/open_camera_dtof --binary sample_vio --board-args 1 192.168.137.100 --seconds 35 --max-packets 120
```

Fallback manual paired capture if needed:

```powershell
.venv\Scripts\python tools\vm_dtof_udp_check.py --seconds 40 --max-packets 120

.venv\Scripts\python tools\board_run.py "cd /opt/sample/open_camera_dtof && timeout 35 ./sample_vio 1 192.168.137.100"
```

Purpose: test whether open_camera's J3/i2c4/pipe2 topology can deliver steady non-zero
dToF frames and official UDP packets.

Risk: starts only the board dToF perception sample and the VM UDP checker. It does not
start MCU bridge, CAN actuator, serial actuator, motor, steering, brake, throttle, or
STM32/chassis control.

Pass gate:

- VM receives official `4873 byte / 40x30 / UDP2368` packets.
- Output is not all or nearly all `2mm`.
- Board logs show sustained processing rather than `get_pipe_frame` timeout.

Fail gate:

- `get_pipe_frame` repeatedly times out.
- UDP is absent or all `2mm`.
- Board crash or kernel panic: stop route1 and do not proceed to RGB/camera mixing.

## Step D - Near-distance gate

Run only after Step C proves steady non-sentinel output. This requires a physical action:
ask the user to place a 30-80cm target in the dToF field of view and wait for completion.

Then rerun the same route1 capture with condition `near_open_camera_dtof_j3`.

Pass gate:

- most valid distances are below 1m for the near target;
- output is not dominated by the `2mm` sentinel;
- VM packet shape remains official `4873 byte / 40x30`.
