#!/usr/bin/env python3
"""
GS1860 pre-warm v5 - CORRECT THEORY:
- pfn_cmos_sensor_global_init pulses GPIO96 in EVERY vi_start registration
- Cold boot: GPIO96 pulse → GS1860 needs 8-9s → driver only waits 1-3s → 92 errors
- Warm boot: GPIO96 pulse → GS1860 needs 1-2s → driver wait is sufficient → SUCCESS

Fix: vi_start #1 (cold boot, 92 errors OK) → sleep(10) → GS1860 warm state
     restart_sensor_isp: pfn_cmos_sensor_global_init → GPIO96 → WARM reset → fast boot
     → pfn_cmos_init succeeds!

NO external GPIO96 pulse needed - the driver handles it automatically.
"""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
VI_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # Restore sample_dtof.c from backup
    print("=== Restoring sample_dtof.c ===")
    out = run(vm, f"cp {SRC}.bak_prewarm {SRC} && echo 'restored'")
    print(out.strip())

    # Check if restart_sensor_isp is already in vi.c
    print("\n=== Checking sample_comm_vi.c for restart_sensor_isp ===")
    out = run(vm, f"grep -n 'restart_sensor_isp' {VI_COMMON}")
    print(out.strip() or "(not found, need to add)")

    if 'restart_sensor_isp' not in out:
        # Need to add it to vi.c
        print("Adding restart_sensor_isp to sample_comm_vi.c...")
        old_vi_header = 'td_s32 sample_comm_vi_start_vi(const sample_vi_cfg *vi_cfg)\n{'
        new_vi_header = (
            'td_s32 sample_comm_vi_restart_sensor_isp(const sample_vi_cfg *vi_cfg)\n'
            '{\n'
            '    sample_comm_vi_stop_isp(vi_cfg);\n'
            '    sleep(1);\n'
            '    return sample_comm_vi_start_isp(vi_cfg);\n'
            '}\n'
            '\n'
            'td_s32 sample_comm_vi_start_vi(const sample_vi_cfg *vi_cfg)\n'
            '{'
        )
        vi_patch = (
            f'old_block = {repr(old_vi_header)}\n'
            f'new_block = {repr(new_vi_header)}\n'
            f'with open({repr(VI_COMMON)}, "r") as f:\n'
            '    content = f.read()\n'
            'if old_block in content:\n'
            '    content = content.replace(old_block, new_block, 1)\n'
            f'    with open({repr(VI_COMMON)}, "w") as f:\n'
            '        f.write(content)\n'
            '    print("VI PATCH OK")\n'
            'else:\n'
            '    print("VI ERROR: pattern not found")\n'
        )
        sftp = vm.open_sftp()
        with sftp.open('/tmp/patch_vi.py', 'w') as f:
            f.write(vi_patch)
        sftp.close()
        out = run(vm, "python3 /tmp/patch_vi.py")
        print(out.strip())
    else:
        print("Already present in vi.c")

    # === Patch sample_dtof.c: v5 approach ===
    # Simple: vi_start #1 (cold) → sleep(10) → restart_sensor_isp (warm)
    # No external GPIO96 pulse - driver handles it via pfn_cmos_sensor_global_init

    old_dtof_block = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }'
    )

    new_dtof_block = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '\n'
        '    /* GS1860 pre-warm v5: cold boot then warm restart */\n'
        '    /* Theory: pfn_cmos_sensor_global_init pulses GPIO96 in every registration */\n'
        '    /* Cold boot: 8-9s; warm boot: 1-2s; driver fixed wait: ~1-3s */\n'
        '    /* So: vi_start #1 = cold (fails OK) → wait 10s → restart = warm (succeeds) */\n'
        '    printf("GS1860 pre-warm: cold start (I2C errors expected, GS1860 booting)...\\n");\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);  /* MCLK on, GPIO96 pulse via driver, 92 I2C errors OK */\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }\n'
        '    sleep(10);  /* wait for GS1860 to fully boot from cold state (~8-9s needed) */\n'
        '\n'
        '    /* GS1860 now in warm state. Restart ISP - driver pulses GPIO96 again */\n'
        '    /* This time GS1860 does warm reset (~1-2s) < driver wait time = SUCCESS */\n'
        '    printf("GS1860 pre-warm: ISP restart (warm reset)...\\n");\n'
        '    ret = sample_comm_vi_restart_sensor_isp(&vi_cfg[1]);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_comm_vi_stop_vi(&vi_cfg[1]);\n'
        '        goto start_dtof_failed;\n'
        '    }\n'
        '    printf("GS1860 pre-warm done!\\n");'
    )

    dtof_patch = (
        f'old_block = {repr(old_dtof_block)}\n'
        f'new_block = {repr(new_dtof_block)}\n'
        f'with open({repr(SRC)}, "r") as f:\n'
        '    content = f.read()\n'
        'if old_block in content:\n'
        '    content = content.replace(old_block, new_block, 1)\n'
        f'    with open({repr(SRC)}, "w") as f:\n'
        '        f.write(content)\n'
        '    print("DTOF PATCH OK")\n'
        'else:\n'
        '    print("DTOF ERROR: not found")\n'
        '    idx = content.find("sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1]")\n'
        '    if idx >= 0:\n'
        '        print("Partial:", repr(content[idx:idx+200]))\n'
    )

    print("\n=== Patching sample_dtof.c (v5) ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_dtof_v5.py', 'w') as f:
        f.write(dtof_patch)
    sftp.close()
    out = run(vm, "python3 /tmp/patch_dtof_v5.py")
    print(out.strip())

    # Verify
    out = run(vm, f"grep -n 'pre-warm v5\\|warm restart\\|restart_sensor_isp\\|cold start\\|warm state' {SRC} | head -10")
    print(f"Verify: {out.strip()}")

    # Rebuild
    print("\n=== Rebuilding ===")
    out = run(vm, f"bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -5'", timeout=120)
    print(out.strip())

    out = run(vm, f"ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof")
    print(f"Binary: {out.strip()}")

    vm.close()

if __name__ == "__main__":
    main()
