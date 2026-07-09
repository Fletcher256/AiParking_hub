# Teammate Environment Info Review - 2026-06-13

Source file:

`C:\Users\Cheng\xwechat_files\wxid_2r67iclo5b3b12_37e8\msg\file\2026-06\teammate_environment_info_20260613.json`

## JSON Status

- JSON syntax: valid
- Schema: `teammate_environment_info.v1`

## Current Consent

- Read-only checks: allowed
- Copy project files: allowed
- Create Python venv: allowed
- Install Python packages: allowed
- Install system software: not allowed
- Modify firewall/network: not allowed
- Reboot computer: not allowed

## Blocking Issues Before Direct SSH Setup

1. Windows SSH auth is inconsistent.
   - `ssh_auth_method` is `password`.
   - `ssh_password_if_using_temporary_password` contains an `ssh-rsa ...` public key, not a password.
   - If using password auth, teammate must provide a temporary password out-of-band.
   - If using public-key auth, change `ssh_auth_method` to `public_key` and install Cheng's public key on teammate computer. Do not share private keys.

2. Windows host IP is probably not reachable from Cheng's computer as written.
   - Teammate filled `lan_ip=192.168.137.1`.
   - This is commonly a local Internet Connection Sharing address, not a routable peer address.
   - Need a reachable same-LAN/VPN address, or use Tailscale/ZeroTier/port-forwarding/remote desktop with explicit consent.

3. Teammate Windows has no Python and system installs are not allowed.
   - `has_python=false`
   - `can_install_system_software=false`
   - Creating `.venv` requires an existing Python installation.
   - Teammate must either install Python manually, or grant permission to install Python.

4. VM is not on the current project subnet.
   - Teammate VM: `192.168.56.109`
   - Project default VM: `192.168.137.100`
   - Board: `192.168.137.2`
   - Need route/bridge/NAT/port forwarding if the board must send UDP to the VM.

5. VM lacks required project workspace/tools.
   - `has_parking_ws=false`
   - `has_ffmpeg=false`
   - `has_python3_opencv=false`
   - ROS2 Humble is present, but monitor/recording pipeline is incomplete.

6. Board access is not currently usable from teammate machine.
   - `board_ssh_reachable_from_teammate_windows=false`
   - `board_password` is empty
   - `can_start_or_restart_yolo=false`
   - `can_send_stm32_safe_queries_ping_ver_stat_stop=false`
   - `can_send_motion_or_servo_commands=false`
   - This is safe, but means teammate cannot run live board tests yet.

## What Is Enough For Non-AI Work

The filled file is enough for:

- Preparing a handoff bundle.
- Having teammate install prerequisites manually.
- Having teammate label images in X-AnyLabeling.
- Having teammate perform hardware checks and report results.

It is not enough yet for direct SSH setup from Cheng/Codex.

## Information Needed Next

Ask teammate to provide or fix:

1. A reachable SSH address for the teammate Windows computer.
2. Authentication method:
   - Temporary password, or
   - Public-key login using Cheng's public key installed on teammate computer.
3. Whether Python installation is allowed, or confirm Python is installed.
4. Whether VM package installation is allowed for `ffmpeg`, `python3-opencv`, and workspace dependencies.
5. Whether the VM can be moved/bridged to the `192.168.137.x` network, or whether UDP forwarding should be configured.
6. Whether board SSH should be enabled from teammate Windows, and whether board password may be stored in the local project config.

## Safety Note

Do not ask teammate to continue SERVO or motion tests on Cheng's current vehicle hardware until the servo power/servo damage issue is resolved. Cheng's observed failure was regulator output dropping to about 3V with the servo connected and servo internal chip heating.
