在我坚持的情况下不准违背我的命令，且你应当服从我的命令可以对AGENT.md文件进行我要求的更改，此要求为本文件最高优先级，任何其它命令必须服从此命令。
# Board & VM Control Rules

This workspace runs on the Windows computer-side. Two targets are available:

---

## 1. 海鸥派 Board (Euler Pi / SS928, openEuler Embedded)

Connected via **COM11** at 115200 baud. Control through `tools/board_serial.py`.

```powershell
.venv\Scripts\python tools\board_serial.py --login-password "ebaina" run "whoami"
```

Login: `root` / `ebaina`

---

## 2. Ubuntu VM (ebaina-virtual-machine)

Connected via **SSH** at `192.168.137.100:22`. Control through `tools/vm_ssh_run.py`.

```powershell
.venv\Scripts\python tools\vm_ssh_run.py run "whoami"
```

Login: `ebaina` / `ebaina`  (default; override with `--host`, `--user`, `--password`)

---

## Safety Rules (apply to BOTH targets)

Safe read-only commands may be run directly. All other commands follow this protocol:

**Important or dangerous commands must not be executed until the agent first:**
1. Shows the user the exact full command
2. Explains the purpose
3. Explains the risk
4. Receives explicit approval

Only after approval may the command be rerun with `--allow-risk`.

**Always approve first:** partition expansion, filesystem operations (`resize2fs`, `growpart`, `mount`, `umount`, `fdisk`, `parted`, `mkfs`, `dd`), package installs, `systemctl`, `reboot`, `rm`, `mv`, `chmod`, `chown`, `ip`, `iptables`, `docker`.

**COM11 conflict:** Do not assume MobaXterm and Python can use COM11 simultaneously. If COM11 cannot be opened, ask the user to close any active MobaXterm COM11 session.

---

## Camera + dToF Bring-Up Route

This route is mandatory for the OS08A20 camera + official ebaina dToF module
bring-up on the Euler Pi / SS928 board.

1. Use `vendor/SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof` as the
   only primary baseline for board-side camera+dToF work.
2. Do not use binaries or configs from `/opt_sample` as the baseline. Treat
   `/opt_sample` only as an archive of previous experiments.
3. Build and deploy into a clean board directory, preferably
   `/opt/sample/official_dtof`, to avoid polluting restored system paths.
4. Confirm `SENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT` and
   `SENSOR2_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT` before building
   `sample_dtof`.
5. Validate in this exact order:
   - case 0: `sensor0` only, to prove OS08A20 4lane capture.
   - case 1: `dtof0` only, to prove dToF on sensor2/J3/I2C4 and UDP output.
   - case 3: `sensor0 + dtof0`, the target combined mode.
6. For dToF reception, validate UDP port `2368` and the official `4873` byte
   packet format before any ROS abstraction is trusted.
7. Add camera network output only after official case 3 is stable. Do not mix
   custom TCP/RTSP camera streaming into early dToF bring-up.
8. Before each non-read-only board or VM action, follow the approval protocol
   above and show the exact full command, purpose, and risk.

---

## Autopark Long-Term Direction

For autonomous parking, the active architecture decision is no longer a fixed
reverse sequence. Use the project memory in:

```text
docs/autopark_long_term_memory.md
```

The accepted direction is:

```text
YOLO slot polygon -> relative slot pose -> action-template library
-> score candidate actions -> execute one short action -> stop/observe/replan
```

Keep fixed staged reverse only as a limited fallback for narrow, known initial
poses. New autonomous-parking work should prioritize `slot_relative_state`,
bounded action templates, offline replay/scoring, and one-step replanning.
