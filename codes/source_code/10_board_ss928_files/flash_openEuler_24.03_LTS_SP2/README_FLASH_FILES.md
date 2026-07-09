# HiEuler Pi / SS928 openEuler 24.03-LTS-SP2 Flash Files

Target board: HiEuler Pi 1 / SS928V100, 4 GB memory variant.

This folder is arranged for ToolPlatform partition-table flashing.

Files to select in ToolPlatform:

- `parttable.xml`

Files referenced by `parttable.xml`:

- `boot_image_4G.bin` -> eMMC `boot`, offset `0`, length `1M`
- `boot_env_4G.bin` -> eMMC `env`, offset `1M`, length `1M`
- `kernel` -> eMMC `kernel`, offset `2M`, length `16M`
- `rootfs.ext4` -> eMMC `rootfs`, offset `18M`, length remaining space

Source files:

- `kernel` copied from official `kernel-pi`
- `rootfs.ext4` copied from official `openeuler-image-hieulerpi1-20250627070055.rootfs.ext4`
- `boot_image_4G.bin`, `boot_env_4G.bin`, `env_append.txt` copied from HiEuler `u-boot` release `v2.0.0`
- `parttable.xml` adapted from the HiEuler official document repository, changed from 8G boot/env files to 4G files because the current board reports `total_mem_size=4G`

Verified SHA256:

- `kernel`: `0914c77d1f9b061b38d6079eaea55ce850dc122c8cc2b5debb18b00842ddec7e`
- `rootfs.ext4`: `44b461083651ef73a2d60e5da5c6196543674b2c62872a6bb7299ca220b3d9af`

Notes:

- Flashing will overwrite the current system on eMMC.
- Use the folder containing this README as ToolPlatform's partition table directory.
- If ToolPlatform asks for a partition table, choose `parttable.xml`.
- Keep the board connected by serial `COM11` and the Ethernet cable connected for TFTP transfer.
