# STM32 USB Serial Bring-Up Status

Scope: Euler Pi / SS928 board receiving STM32 data through a CH340/CH341 USB
serial cable. This is receive-only work and must not send actuator commands.

## Current Evidence

- The USB cable enumerates on the board as `VID:PID 1a86:7523`, product
  `USB Serial`.
- The board did not create a serial device automatically.
- The board has `usbserial_generic` and `option` available, but no visible
  `ch341` module under `/lib/modules`.
- The board has no `gcc` or `make`, so building a kernel module directly on
  the board is not currently available.
- Binding `1a86:7523` through `usbserial_generic` created `/dev/ttyUSB0`.
- `/dev/ttyUSB0` receives bytes at the STM32 side baud rate `9600 8N1`, but
  the observed sample is not readable ASCII.
- On 2026-05-30, the receive-only end-to-end path passed with the board and
  VM on the wired `192.168.137.0/24` network:
  `STM32_END_TO_END_CHECK PASS`, `44480` raw bytes, `1389` chunks, `0` bad UDP
  packets recorded by the VM ROS2 receiver.
- The current STM32 stream is classified by the VM ROS2 receiver as
  `binary_with_nul` / protocol family `binary`, not plain ASCII text.
- The board now has a CH340/CH341 hotplug helper installed:
  `/etc/udev/ch341-autobind.sh` plus
  `/etc/udev/rules.d/98-ch341-autobind.rules`. It records the active driver
  state in `/tmp/stm32_usb_serial_driver_status.json`.
- On 2026-05-30, `tools/stm32_link_manager.py start --allow-risk`, `health`,
  and `stop --allow-risk` were verified as the host-side repeatable operation
  path. The latest live VM session wrote
  `/home/ebaina/parking_sensor_records/stm32_ros_live/run_20260530_162539`
  with `58560` raw bytes and final protocol classification
  `binary_with_nul` / `binary`. A post-stop VM process check found no
  remaining `stm32_udp_bridge`/`parking_stm32_udp_bridge` process.
- On 2026-05-30, `tools/sensor_suite_manager.py start --allow-risk`,
  `health`, `stop --allow-risk`, and `latest-session` were verified as the
  repeatable full perception operation path for camera + dToF + STM32. The
  latest full VM run wrote
  `/home/ebaina/parking_sensor_records/sensor_suite_live/run_20260530_180454`
  with `53` camera frames, `598` parsed dToF metadata rows, `86` sync pairs,
  and `62464` STM32 raw bytes. During the live health check, camera, dToF, and
  STM32 were all healthy; after stop, both board-side processes and both ROS2
  child nodes exited cleanly with no residual perception process.
- On 2026-05-30, `tools/parking_link_acceptance.py --run-sec 35` completed as
  `PARKING_LINK_ACCEPTANCE WARN` with all functional acceptance checks passing.
  The report is
  `D:\parking_board_agent\artifacts\parking_link_acceptance\acceptance_20260530_180557.json`.
  The only expected warnings are the current `generic_fallback` driver mode and
  the missing matching `4.19.90` kernel inputs for the formal CH341 route.
- On 2026-05-30, after a user-confirmed physical board reboot,
  `tools/post_replug_validation.py
  --stm32-vm-duration-sec 25 --stm32-board-duration-sec 15` completed as
  `POST_REPLUG_VALIDATION WARN`.
  The report is
  `D:\parking_board_agent\artifacts\post_replug_validation\post_replug_20260530_180414.json`.
  It recorded `36096` STM32 raw bytes through the VM ROS2 check path and again
  confirmed no residual sensor process and no forbidden control process.
- On 2026-05-30, `tools/parking_goal_status.py` completed as
  `PARKING_GOAL_STATUS WARN`. The report is
  `D:\parking_board_agent\artifacts\parking_goal_status\status_20260530_180621.json`.
  It summarizes the objective-level evidence and leaves only the expected
  formal CH341 gap as a warning.
- On 2026-05-30, after unplugging the board Ethernet cable,
  `tools\wifi_sensor_suite_manager.py start --allow-risk`, `health`,
  `stop --allow-risk`, and `latest-session` were verified as the same-Wi-Fi
  full receive path. The board was auto-discovered at `172.20.10.2` on SSID
  `iPhone`; the Windows host forwarded dToF UDP `2368` and STM32 UDP `24680`
  to the VM at `192.168.247.129`. The VM record root was
  `/home/ebaina/parking_sensor_records/sensor_suite_wifi/run_20260530_190838`
  with `130` camera frames, `1546` parsed dToF metadata rows, `209` sync
  pairs, and `137728` STM32 raw bytes. The live UDP forwarder health showed
  `0` forwarding errors.

## Wired Ethernet State

The current working wired path is:

```text
STM32 -> CH340/CH341 USB serial -> Euler Pi eth0 192.168.137.2
  -> UDP 24680 -> Ubuntu VM 192.168.137.100 -> ROS2 parking_bridge
```

The board originally had `eth0=192.168.1.168/24`, while the Windows wired
adapter and VM were on `192.168.137.0/24`. A board-side address was added with:

```sh
ip addr add 192.168.137.2/24 dev eth0
ip link set eth0 up
```

To keep this address after reboot, the same alias is installed as
`/etc/init.d/S81wired137` on the board. The local source copy is
`tools/board_wired_137_init.sh`. A late boot repair script,
`/etc/init.d/S99parkinglink`, reruns the wired alias and USB serial status
helper after the rest of the network scripts have run. This does not remove the
original `192.168.1.168/24` address; it only adds the direct Windows/VM link
address.

Connectivity evidence after adding the temporary address:

- Board `192.168.137.2` pinged Windows wired adapter `192.168.137.1`.
- Board `192.168.137.2` pinged VM `192.168.137.100`.
- VM received a one-packet UDP smoke test from board source
  `192.168.137.2`.
- The VM ROS2 STM32 receiver recorded the full STM32 serial stream forwarded
  from the board.

## Driver Assessment

The reliable long-term solution is a kernel that has Linux `ch341` support
enabled or a matching `ch341.ko` built for the running board kernel:

- Running kernel: `Linux 4.19.90 #1 SMP Fri Jan 30 11:45:17 CST 2026 aarch64`.
- Local firmware patch material contains multiple kernel config fragments.
  The checked `vendor/HiEuler_hardware_driver_unzip/hardware_driver-master/linux/5.10.0-153.28.0.patch`
  file has conflicting 4.19.90 defconfig evidence:
  `hieulerpi1_defconfig` sets `CONFIG_USB_SERIAL_CH341=y`, while
  `ss928v100_emmc_defconfig` sets `# CONFIG_USB_SERIAL_CH341 is not set`.
  The running board boots from `mmcblk0`/`root=/dev/mmcblk0p5`, and behaves
  like the eMMC-style configuration where CH341 is not active.
- No ready-to-load `ch341.ko` was found in the current local vendor payloads.
- Local search found firmware images, prebuilt media/driver `.ko` files, and
  kernel patches, but not a complete ready-to-build kernel source tree with
  `drivers/usb/serial/ch341.c` and matching generated module metadata.
- Linux mainline identifies `1a86:7523` as a CH340 serial converter handled by
  `drivers/usb/serial/ch341.c` / `CONFIG_USB_SERIAL_CH341`.
- WCH's official Linux UART driver line for CH340/CH341 is
  `WCHSoftGroup/ch341ser_linux`. It must be compiled against the target board
  kernel headers/source to produce a loadable module for this board. The WCH
  README says a successful build produces `ch341.ko`; the vendor driver creates
  `/dev/ttyCH341USBx`, while the Linux mainline driver normally creates
  `/dev/ttyUSBx`.
- The local official WCH README also states that Linux has had a built-in
  `drivers/usb/serial/ch341.c` driver since mainline kernel `2.6.24`, but WCH
  recommends its own driver when the built-in driver is not sufficient. On this
  board, neither a built-in active `ch341` path nor a matching WCH-built module
  is currently available.
- The official WCH source has been downloaded locally to
  `vendor/WCHSoftGroup_ch341ser_linux`. This provides `driver/ch341.c`,
  `driver/ch341.h`, and `driver/Makefile`, but it is not enough by itself:
  a matching board kernel build tree/headers for `4.19.90` are still required.
- The local vendor payload currently contains `ch343ser_linux-main`, which is
  for CH342/CH343/CH344/CH346/CH347/CH339/CH910x-class devices, not the
  observed `1a86:7523` CH340/CH341 adapter. Do not treat it as the formal
  solution for this cable.

Practical driver route:

1. Keep the current `usbserial_generic` path only as a bounded validation path.
2. Prefer a board image/kernel config where `CONFIG_USB_SERIAL_CH341=y` is
   enabled for the running `4.19.90` board kernel, or obtain the exact matching
   kernel tree/headers and build a matching `ch341.ko`.
3. Do not try to install the local `ch343.ko` as the solution for the current
   `1a86:7523` adapter; it is the wrong driver family.
4. A hardware fallback that still satisfies "reliable alternative" is to use a
   USB serial adapter whose driver is already active in the board image, then
   validate it with the same receive-only capture and ROS2 pipeline.

References:

- https://cateee.net/lkddb/web-lkddb/USB_SERIAL_CH341.html
- https://linux-hardware.org/index.php?id=usb%3A1a86-7523
- https://codebrowser.dev/linux/linux/drivers/usb/serial/ch341.c.html
- https://github.com/WCHSoftGroup/ch341ser_linux
- https://gitee.com/HiEuler/hardware_driver

Until a matching `ch341` driver is available, `usbserial_generic` is a useful
temporary receive path. It is not the preferred production solution because the
kernel warns it is for testing and one-off prototypes.

The current temporary path is explicitly labeled, not hidden:

```json
{"status":"serial_ready","tty":"/dev/ttyUSB0","driver":"generic","driver_mode":"generic_fallback"}
```

The board UDP bridge includes `serial_driver` and `serial_driver_mode` in
startup, health, and serial chunk metadata. The VM check prints those fields so
future logs can prove whether the path is formal `ch341` or fallback generic.

## Reusable Tools

- `tools/board_auto_ssh.py`: host-side automatic same-Wi-Fi board discovery
  and SSH control helper. It scans active local IPv4 networks and the ARP cache,
  prioritizes the observed board Wi-Fi MAC `38:7a:cc:e9:db:1a`, and can run
  safe board commands without relying on COM11 or a fixed `192.168.137.2`.
  Its file upload path falls back from SFTP to SSH/base64 writing for board
  SSH servers that do not expose SFTP.
- `tools/board_usb_serial_check.sh`: board-side read-only USB serial state check.
- `tools/board_usb_serial_bind_generic.sh`: board-side temporary generic bind.
- `tools/board_ch341_autobind.sh`: board-side hotplug helper that prefers an
  existing formal CH341 driver and only falls back to `usbserial_generic` if no
  tty exists. Installed on the board as `/etc/udev/ch341-autobind.sh`.
- `tools/board_ch341_autobind.rules`: udev rule installed as
  `/etc/udev/rules.d/98-ch341-autobind.rules`.
- `tools/board_stm32_usb_serial_capture.sh`: board-side capture and metadata
  helper. It can bind generic if needed, configure `9600 8N1`, record raw data,
  write a hex dump, and print a short status summary.
- `tools/stm32_serial_analyze.py`: host-side analyzer for raw capture files.
  It uses the same protocol-shape logic as ROS2 and reports whether the stream
  looks like ASCII, binary, mixed, or empty data.
- `tools/stm32_board_capture.py`: host-side approval-gated wrapper. It uploads
  the board helper, runs a receive-only capture, fetches the raw bytes back into
  `artifacts/stm32_serial`, and writes `analysis.json`.
- `tools/board_stm32_usb_serial_udp_bridge.py`: board-side receive-only UDP
  forwarder. It reads the USB serial stream and sends `STM32USB1` UDP datagrams
  to the VM without writing bytes back to STM32.
- `tools/stm32_board_udp_bridge.py`: host-side approval-gated launcher for a
  bounded board-side UDP forwarding validation run.
- `ros/parking_bridge/parking_bridge/stm32_udp_bridge.py`: VM-side ROS2 node
  that receives those UDP datagrams, publishes `/parking/stm32/*` topics,
  records raw bytes and metadata, emits health snapshots, and includes rolling
  ASCII/binary protocol analysis in `/parking/stm32/health`.
- `ros/parking_bridge/parking_bridge/stm32_protocol.py`: shared STM32 serial
  protocol-shape analyzer used by ROS2 and the offline analysis tool.
- `ros/parking_bridge/launch/stm32.launch.py`: STM32-only launch file for
  validating the serial path without starting camera or dToF receivers.
- `tools/vm_stm32_ros_check.py`: approval-gated VM-side ROS2 validation run.
- `tools/stm32_end_to_end_check.py`: approval-gated orchestrator that deploys
  the ROS2 package, starts the VM STM32 receiver, starts the board serial UDP
  forwarder, and reports an end-to-end PASS/FAIL.
- `tools/ch341_readiness_check.py`: read-only checker for the formal CH340/CH341
  driver route. It inspects local vendor files, official WCH source, local
  defconfig CH341 settings, and VM toolchain/kernel inputs.
- `tools/build_ch341_for_board.py`: VM-side official WCH CH341 build helper.
  It uploads the official driver source and refuses to build unless the supplied
  kernel build tree reports the expected board release `4.19.90`. It does not
  load or install the module.
- `tools/board_udp_smoke_send.py`: board-side one-packet UDP smoke-test sender.
- `tools/vm_udp_smoke_listen.py`: VM-side one-packet UDP smoke-test listener.
- `tools/board_wired_137_init.sh`: board init snippet installed as
  `/etc/init.d/S81wired137` to keep `eth0` reachable as `192.168.137.2/24`.
- `tools/board_parking_link_init.sh`: board late-boot repair snippet installed
  as `/etc/init.d/S99parkinglink`. It reruns the wired alias and the
  CH340/CH341 status helper after boot, writing `/tmp/parking_link_init.log`.
- `tools/stm32_link_manager.py`: host-side manager for the receive-only
  STM32 link. It provides `deploy`, `start`, `stop`, `health`, `logs`,
  `check`, and `latest-analysis` actions while keeping board and VM logs in
  fixed locations.
- `tools/sensor_suite_manager.py`: host-side manager for the receive-only
  camera + dToF + STM32 perception suite. It starts the VM ROS2
  `parking.launch.py` receiver first, then the board STM32 UDP forwarder, and
  finally the official board `/opt/sample/official_dtof/sample_dtof_rtsp 7`
  case. This ordering avoids COM11 command corruption from case7 kernel/module
  logs while still using the official dToF baseline. Its stop path uses a
  bounded background FIFO write for `case7.stdin`, so a stale FIFO without a
  reader cannot block the COM11 shell.
- `tools/udp_forwarder.py`: host-side UDP relay used when the VM is reachable
  through VMware NAT/host-only networking but the board is only on the same
  Wi-Fi/hotspot as the Windows host.
- `tools/wifi_sensor_suite_manager.py`: same-Wi-Fi full sensor manager. It
  auto-discovers the board over Wi-Fi, starts the host UDP relay, starts the VM
  ROS2 `parking.launch.py` receiver using the board Wi-Fi RTSP URL, starts the
  board STM32 receive-only UDP bridge, and starts official case7 with the
  Windows host as UDP destination.
- `tools/parking_link_acceptance.py`: end-to-end receive-only acceptance
  runner. It performs pre-stop, audit, start, timed collection, health, clean
  stop, latest-session summary, and final audit, then writes a JSON report under
  `artifacts\parking_link_acceptance`.
- `tools/post_replug_validation.py`: post-power-cycle, post-USB-replug, or
  migration validation runner. By default it validates the STM32 receive-only
  path and latest VM-side protocol analysis without starting camera+dToF; pass
  `--full-sensor` when the full camera+dToF+STM32 acceptance run is required.
- `tools/parking_link_audit.py`: read-only full-state audit for the board,
  VM, latest sensor records, driver mode, formal CH341 gap, residual sensor
  processes, and forbidden control processes. Current expected result is
  `PARKING_LINK_AUDIT WARN` because the serial adapter still uses
  `generic_fallback`.
- `tools/parking_goal_status.py`: read-only objective-level status report. It
  combines live audit output, the latest acceptance/post-replug artifacts,
  source invariants, and documentation checks into
  `artifacts\parking_goal_status\status_*.json`.
- `tools/vm_print_latest_stm32_analysis.py`: VM-side latest-analysis reader.
  It now queries the VM through `tools/vm_ssh_run.py` instead of trying to
  read `/home/ebaina/...` from the Windows host, and searches both
  `stm32_ros_check`, `stm32_ros_live`, and `sensor_suite_live` record roots by
  default.
- `docs/perception_link_runbook.md`: operational runbook for quick audit,
  full receive-only run, STM32-only run, record layout, reboot/USB replug
  checks, migration, and the formal CH341 gap.

## Current Board Check

As of the latest read-only check, the adapter is still present as
`1a86:7523`, `/dev/ttyUSB0` exists, and the active attachment is still
`usbserial_generic`. Kernel logs still warn that the generic driver is intended
for testing and prototypes.

Current driver status file:

```text
/tmp/stm32_usb_serial_driver_status.json
status=serial_ready
tty=/dev/ttyUSB0
driver=generic
driver_mode=generic_fallback
```

Read-only connectivity checks currently pass:

- VM SSH target `192.168.137.100` logs in as `ebaina` on
  `ebaina-virtual-machine`.
- Board console over COM11 logs in as `root` and has `/usr/local/bin/python3`.
- Board Python has the needed `termios` baud constants including `B9600`.
- The VM has the current `parking_bridge` deployed and built under
  `/home/ebaina/parking_ws`.
- VM has cross-compilers and `make`, but does not currently have matching
  `4.19.90` board kernel headers/source under the checked standard locations.
- `tools/ch341_readiness_check.py --json` currently reports
  `has_official_ch341_driver_source=true`,
  `has_matching_kernel_inputs=false`, `has_ready_ch341_module=false`, and
  `can_build_or_install_now=false`. Its defconfig scan now reports
  `hieulerpi1_defconfig:y` and `ss928v100_emmc_defconfig:not_set`.

## Approval-Gated Capture Recipe

Preview the exact commands, purpose, and risk:

```powershell
.venv\Scripts\python tools\stm32_board_capture.py
```

After explicit approval, run:

```powershell
.venv\Scripts\python tools\stm32_board_capture.py --allow-risk
```

This is receive-only. It does not write bytes to STM32 and does not start any
MCU, CAN, motor, steering, brake, throttle, or actuator process. It may still
open the serial port and affect DTR/RTS lines, so a reset-prone STM32 board may
restart when the port is opened.

## Next Gates

1. Ask STM32 to emit a known ASCII test pattern such as `STM32_HELLO\r\n` or
   repeated `U` (`0x55`) at `9600 8N1`.
2. Capture through `/dev/ttyUSB0`.
3. If the ASCII pattern is readable, proceed with a receive-only protocol parser.
4. If the ASCII pattern is still garbled, prioritize a proper `ch341` driver or
   a USB serial adapter with a driver already active in the board image.
5. After a stable receive path is proven, bridge records/status into the VM ROS2
   workflow without sending STM32 actuator commands.

## ROS2 Integration Path

The intended data path is:

```text
STM32 UART TX -> CH340/CH341 USB serial -> Euler Pi /dev/ttyUSB0
  -> board_stm32_usb_serial_udp_bridge.py receive-only UDP
  -> VM parking_bridge stm32_udp_bridge
  -> /parking/stm32/raw, /parking/stm32/metadata, /parking/stm32/health
```

The VM launch file now includes the STM32 UDP receiver by default:

```bash
ros2 launch parking_bridge parking.launch.py stm32_udp_port:=24680
```

For STM32-only testing:

```bash
ros2 launch parking_bridge stm32.launch.py stm32_udp_port:=24680
```

The board-side UDP forwarder must still be started only after explicit approval
because it opens `/dev/ttyUSB0`, may bind through `usbserial_generic`, and may
write record files under `/tmp`.

Preferred repeatable host-side operation path:

```powershell
.venv\Scripts\python tools\stm32_link_manager.py start --allow-risk
.venv\Scripts\python tools\stm32_link_manager.py health
.venv\Scripts\python tools\stm32_link_manager.py logs
.venv\Scripts\python tools\stm32_link_manager.py stop --allow-risk
.venv\Scripts\python tools\stm32_link_manager.py latest-analysis
```

The manager starts only the receive-only board serial UDP forwarder and the VM
ROS2 STM32 receiver. It does not start camera/dToF samples, MCU bridge, CAN,
motor, steering, brake, throttle, or actuator code. The VM side uses a fixed
state directory under `/tmp/parking_stm32_link`, records under
`/home/ebaina/parking_sensor_records/stm32_ros_live`, and stops the ROS2
receiver by process group plus a narrow STM32 receiver cleanup fallback so a
`ros2 launch` parent cannot leave a stale `stm32_udp_bridge` child behind.

Preferred full camera + dToF + STM32 perception operation path:

```powershell
.venv\Scripts\python tools\sensor_suite_manager.py deploy --allow-risk
.venv\Scripts\python tools\sensor_suite_manager.py start --allow-risk
.venv\Scripts\python tools\sensor_suite_manager.py health
.venv\Scripts\python tools\sensor_suite_manager.py stop --allow-risk
.venv\Scripts\python tools\sensor_suite_manager.py latest-session
```

This manager uses the official board baseline:

```text
/opt/sample/official_dtof/sample_dtof_rtsp 7 192.168.137.100
```

It records the VM side under
`/home/ebaina/parking_sensor_records/sensor_suite_live/run_*`, including:

- `session_*/camera_frames/*.jpg`
- `session_*/dtof_packets.bin`
- `session_*/dtof_metadata.jsonl`
- `session_*/sync_pairs.jsonl`
- `stm32_session_*/stm32_serial_raw.bin`
- `stm32_session_*/stm32_protocol_analysis.json`

Latest full-suite validation result:

```text
VM_RECORD_DIR /home/ebaina/parking_sensor_records/sensor_suite_live/run_20260530_164612
VM_CAMERA_FRAMES 73
VM_DTOF_METADATA_LINES 880
VM_SYNC_LINES 124
VM_ANY_BOTH_OK True
VM_STM32_RAW_BYTES 82496
VM_STM32_CLASSIFICATION binary_with_nul
VM_STM32_PROTOCOL_FAMILY binary
BOARD_CASE7_EXIT_CODE 0
BOARD_STM32_LOG_ISSUES none
VM_RESIDUAL_PROCESSES none
```

Read-only full-state audit command:

```powershell
.venv\Scripts\python tools\parking_link_audit.py
```

Latest audit result:

```text
PARKING_LINK_AUDIT WARN
PASS board_console
PASS vm_ssh
PASS board_wired_192_168_137_2
PASS board_usb_serial_ready
WARN board_ch341_driver_mode - driver_mode=generic_fallback
PASS board_official_case7_binary
PASS board_no_residual_sensor_processes
PASS board_no_forbidden_control_processes
PASS vm_ros2_workspace_ready
PASS vm_latest_camera_dtof_record
PASS vm_latest_stm32_record
PASS vm_no_residual_sensor_processes
PASS vm_no_forbidden_control_processes
WARN formal_ch341_route - missing matching 4.19.90 kernel inputs
```

Latest formal-driver readiness detail:

```text
defconfig_ch341_setting=hieulerpi1_defconfig:y
defconfig_ch341_setting=ss928v100_emmc_defconfig:not_set
board_cmdline=root=/dev/mmcblk0p5
board_usb_serial_drivers=generic,option1
vm_4_19_90_kernel_inputs=none
ready_ch341_ko=none
```

Preview the exact board-side UDP forwarding commands:

```powershell
.venv\Scripts\python tools\stm32_board_udp_bridge.py
```

After approval, run a bounded 30-second validation:

```powershell
.venv\Scripts\python tools\stm32_board_udp_bridge.py --allow-risk
```

Preview the exact VM-side STM32 ROS2 check command:

```powershell
.venv\Scripts\python tools\vm_stm32_ros_check.py
```

The VM-side check uses a fresh run directory under
`/home/ebaina/parking_sensor_records/stm32_ros_check` each time, so stale
records from an earlier run cannot create a false PASS. The run directory is
passed into the post-check Python process through `RECORD_DIR_FOR_PY`, avoiding
shell heredoc expansion problems.

For the full bounded end-to-end check, preview:

```powershell
.venv\Scripts\python tools\stm32_end_to_end_check.py
```

After approval, run:

```powershell
.venv\Scripts\python tools\stm32_end_to_end_check.py --allow-risk
```

The end-to-end wrapper now reports command timeouts as explicit FAIL evidence
instead of leaving a Python traceback, and it terminates the VM receiver process
if the receiver exceeds its timeout.

The end-to-end wrapper also passes the same VM host/user/password parameters to
the deploy step, the VM ROS2 receiver step, and the board UDP forwarding target.
Its approval preview prints the fully parameterized command that will be run.

Latest wired validation command:

```powershell
.venv\Scripts\python tools\stm32_end_to_end_check.py --vm-host 192.168.137.100 --vm-user ebaina --vm-password ebaina --udp-port 24680 --vm-duration-sec 45 --board-duration-sec 30 --receiver-warmup-sec 6 --allow-risk
```

Latest result:

```text
STM32_RAW_BYTES 44288
STM32_CHUNK_LINES 1383
STM32_HEALTH_LINES 75
STM32_ROS_CHECK PASS
STM32_END_TO_END_CHECK PASS
```

Latest protocol-analysis validation result:

```text
STM32_RAW_BYTES 26336
STM32_CHUNK_LINES 822
STM32_HEALTH_LINES 48
STM32_SERIAL_DRIVER generic
STM32_SERIAL_DRIVER_MODE generic_fallback
STM32_PROTOCOL_CLASSIFICATION binary_with_nul
STM32_PROTOCOL_FAMILY binary
STM32_PRINTABLE_ASCII_RATIO 0.064208984375
STM32_ENTROPY_BITS_PER_BYTE 3.072323607496291
STM32_ROS_CHECK PASS
STM32_END_TO_END_CHECK PASS
```

The corresponding final analysis file reported `newline_count=0`,
`carriage_return_count=0`, and `line_count=0`, so the binary classification is
not an artifact of ASCII line parsing.

To re-check formal CH341 driver readiness without modifying board or VM state:

```powershell
.venv\Scripts\python tools\ch341_readiness_check.py
```

To build the official WCH driver after obtaining a matching board kernel build
tree on the VM:

```powershell
.venv\Scripts\python tools\build_ch341_for_board.py --kernel-dir /path/to/ss928-4.19.90-kernel-build --allow-risk
```

This helper intentionally failed against the VM's Ubuntu
`/usr/src/linux-headers-6.8.0-111-generic` because the kernel release marker
does not match the board's `4.19.90` kernel. That confirms the guard is working
and prevents building a useless module for the wrong kernel.
