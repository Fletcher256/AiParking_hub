# dToF Next-Step Notes

Date: 2026-05-26

## What Worked

- Board kernel matches the official `HiEuler/open_camera` dToF modules:
  - `ot_isp.ko`
  - `ot_mipi_rx.ko`
  - `ot_vi.ko`
- `init_dtof_cfg.sh` runs successfully and only toggles the dToF reset GPIO.
- `sample_vio` reaches dToF initialization and prints:
  - `DTOF version: F01V01T01`
  - `DtofInit success!!!`
  - repeated `distance[14][19] = 2`

## What Broke

- The full `sample_vio` path crashes the kernel in `ot_isp`:
  - `Kernel panic - not syncing: stack-protector: Kernel stack is corrupted in: isp_get_frame_edge+0x218/0x220 [ot_isp]`
- The crash happens after the dToF pipeline has already started, which suggests the RGB / ISP path inside `sample_vio` is the unstable part.
- Do not rerun `/etc/init.d/S90AutoRun` as-is. It also loads unrelated modules such as `plat_soc.ko`, `wifi_soc.ko`, `ble_soc.ko`, `sle_soc.ko`, and `load_riscv`, which were part of the bad boot sequence.

## Best Next Build Direction

Build a dToF-only variant from:

- `vendor/HiEuler_open_camera_unzip/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c`

Recommended source change:

```c
#define SUPPORT_RGB 0
#define SUPPORT_DTOF 1
```

This should remove the RGB / ISP startup path and keep only the dToF flow.

Rebuild from the `mipi_rgb_dtof/code/mipi_imx347` directory in the Ubuntu VM using the same SS928 cross-toolchain that already worked for your `sample_dtof` build, then copy the new `sample_vio` back to:

- `/root/sample_vio`

## Board-Side Minimal Sequence to Keep

1. Load the base media stack with `load_ss928v100`
2. Run `/root/init_dtof_cfg.sh`
3. Start the dToF-only binary

## Current Board Files

- `/ko/ot_isp.ko`
- `/ko/ot_mipi_rx.ko`
- `/ko/ot_vi.ko`
- `/root/dtof.ini`
- `/root/gs1860_register.ini`
- `/root/init_dtof_cfg.sh`
- `/root/sample_vio`

## PC Network

- Windows wired NIC:
  - `192.168.137.1/24`
- Board temporary alias used earlier:
  - `192.168.137.2/24`

## Reminder

Do not execute `resize2fs`, `growpart`, `fdisk`, `parted`, `mkfs`, `dd`, `mount`, `umount`, or `reboot` without explicit approval.
