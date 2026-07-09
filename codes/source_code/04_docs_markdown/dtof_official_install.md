# Official dToF Package Install Notes

Date: 2026-05-26

## Source

Official Gitee repository:

```text
https://gitee.com/hieulerpi/SS928V100_SDK_V2.0.2.2_MPP_Sample
```

Local copy:

```text
D:\parking_board_agent\vendor\SS928V100_SDK_V2.0.2.2_MPP_Sample-master
```

Ubuntu build zip:

```text
D:\parking_board_agent\vendor\SS928V100_dtof_build_source.zip
```

## Board Install Status

Original board modules were backed up to:

```text
/root/dtof_backup/ko
```

Official dToF modules and config were staged at:

```text
/root/dtof_official
```

Installed official dToF modules:

```text
/ko/ot_isp.ko
/ko/ot_mipi_rx.ko
/ko/ot_vi.ko
```

MD5 after install:

```text
34e6a7cc90b0528080015b09511c7f4c  /ko/ot_isp.ko
cb6114053c84e4abc55f4f0a783698ba  /ko/ot_mipi_rx.ko
9691408cddb1fb7b98581b09528d04ee  /ko/ot_vi.ko
```

Runtime working directory:

```text
/root/dtof_work
```

Current contents:

```text
dtof.ini
dtof_init.sh
gs1860_register.ini
```

`sample_dtof` still needs to be cross-compiled in the Ubuntu VM and copied to `/root/dtof_work/sample_dtof`.

## Ubuntu Build

Copy `vendor/SS928V100_dtof_build_source.zip` to the Ubuntu VM, unzip it, then run:

```bash
cd SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/dtof
make clean || true
make OS_TYPE=linux CROSS_COMPILE=aarch64-mix210-linux-
file sample_dtof
```

If the VM toolchain prefix is different, adjust `CROSS_COMPILE`.

Expected output:

```text
sample_dtof: ELF 64-bit LSB pie executable, ARM aarch64
```

## Board Runtime Plan

After `sample_dtof` is available:

```sh
cd /root/dtof_work
./dtof_init.sh
./sample_dtof 1 <host-ip>
```

Case `1` is `one dtof0`, using `1lane sensor2`, according to the official sample usage.

The board should be rebooted or the media modules should be reloaded before validating, because the installed dToF `.ko` files are used when `/etc/init.d/S90AutoRun` loads the media stack.
