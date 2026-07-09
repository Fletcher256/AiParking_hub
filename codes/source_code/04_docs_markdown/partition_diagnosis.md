# Partition Diagnosis

Date: 2026-05-25

Status: serial link verified; read-only partition diagnosis completed; approved filesystem expansion completed successfully.

## Board Summary

- Login user: `root`
- Hostname: `hieulerpi1`
- OS: `openEuler Embedded Reference Distro latest (oEE)`
- Kernel: `Linux hieulerpi1 5.10.0-openeuler #1 SMP Tue Apr 14 02:12:35 UTC 2026 aarch64`

## Read-Only Findings

`df -h` reports:

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/root       566M  471M   51M  91% /
```

`findmnt -n -o SOURCE,FSTYPE,SIZE,AVAIL /` reports:

```text
/dev/mmcblk0p4 ext4   565.3M 50.8M
```

`cat /proc/partitions` reports the eMMC and partitions:

```text
179        0   30535680 mmcblk0
179        1       1024 mmcblk0p1
179        2       1024 mmcblk0p2
179        3      16384 mmcblk0p3
179        4   30517248 mmcblk0p4
```

`blkid || true` reports:

```text
/dev/mmcblk0p4: UUID="e64ce122-9ce3-4ef2-90cf-6fa09f7effe0" BLOCK_SIZE="4096" TYPE="ext4"
```

`lsblk -f || true` reports `/dev/mmcblk0p4` as ext4 mounted at `/`, with about `50.8M` available.

`mount | grep ' on / '` reports:

```text
/dev/mmcblk0p4 on / type ext4 (rw,relatime)
```

## Diagnosis

1. Root filesystem actual device: `/dev/mmcblk0p4`.
2. Filesystem type: `ext4`.
3. The root filesystem is only about `565M` because the ext4 filesystem has not been grown to match the larger underlying partition.
4. The partition `/dev/mmcblk0p4` is already about `30,517,248` KiB, roughly `29.1G`, so `growpart` probably is not needed.
5. The most likely required operation is only `resize2fs /dev/mmcblk0p4`.
6. Online expansion is likely possible because root is mounted read-write as ext4, but it still must be explicitly approved before running.

## Suggested Command Requiring Approval

```sh
resize2fs /dev/mmcblk0p4
```

Purpose: grow the ext4 root filesystem to use the already-large `/dev/mmcblk0p4` partition.

Risk: modifies filesystem metadata on the live root filesystem. If the wrong device is used, the filesystem is damaged, or the board loses power during the operation, data loss or boot failure is possible.

## Commands That Are Not Currently Recommended

```sh
growpart /dev/mmcblk0 4
```

Reason: current read-only data shows partition 4 already spans almost the whole eMMC, so growing the partition first does not appear necessary.

Risk: modifies the partition table and can make the board unbootable if used incorrectly.

```sh
fdisk /dev/mmcblk0
parted /dev/mmcblk0
mkfs ...
dd ...
mount ...
umount ...
reboot
```

Risk: these can alter storage layout, destroy data, disrupt the running root filesystem, or interrupt the board.

Before explicit user approval, do not execute `resize2fs`, `growpart`, `fdisk`, `parted`, `mkfs`, `dd`, `mount`, `umount`, or `reboot`.

## Approved Expansion Result

The user approved this exact command:

```sh
resize2fs /dev/mmcblk0p4
```

It completed successfully with exit code `0`.

Key output:

```text
Filesystem at /dev/mmcblk0p4 is mounted on /; on-line resizing required
old_desc_blocks = 1, new_desc_blocks = 4
EXT4-fs (mmcblk0p4): resizing filesystem from 158987 to 7629312 blocks
EXT4-fs (mmcblk0p4): resized filesystem to 7629312
The filesystem on /dev/mmcblk0p4 is now 7629312 (4k) blocks long.
```

Post-expansion `df -h`:

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/root        28G  471M   26G   2% /
```

Post-expansion `findmnt -n -o SOURCE,FSTYPE,SIZE,AVAIL /`:

```text
/dev/mmcblk0p4 ext4   27.3G 25.7G
```

Final conclusion: the root ext4 filesystem has been expanded successfully. No `growpart`, `fdisk`, `parted`, `mkfs`, `dd`, `mount`, `umount`, or `reboot` command was executed.
