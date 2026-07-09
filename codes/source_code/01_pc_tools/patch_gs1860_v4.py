#!/usr/bin/env python3
"""
GS1860 pre-warm v4 - THE RIGHT FIX:
- Keep MCLK running throughout (never call vi_stop during pre-warm)
- After GPIO96 pulse + 10s wait, restart ONLY the ISP thread
- ISP restart retries sensor I2C init with GS1860 now responding

Changes:
1. sample_comm_vi.c: add sample_comm_vi_restart_sensor_isp() (non-static wrapper)
2. sample_dtof.c: pre-warm calls restart_sensor_isp instead of vi_stop+vi_start
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

    # === PATCH 1: sample_comm_vi.c - add restart_sensor_isp function ===
    # Add the non-static wrapper AFTER the static sample_comm_vi_stop_isp function
    # We'll append it just before sample_comm_vi_start_vi

    print("\n=== Backup sample_comm_vi.c ===")
    out = run(vm, f"cp {VI_COMMON} {VI_COMMON}.bak_prewarm && echo 'backed up'")
    print(out.strip())

    # The wrapper to add to sample_comm_vi.c
    # It goes right before sample_comm_vi_start_vi (which is at line 1881)
    new_func_c = (
        '\n'
        '/* GS1860 pre-warm: restart only ISP sensor init without stopping MCLK */\n'
        'td_s32 sample_comm_vi_restart_sensor_isp(const sample_vi_cfg *vi_cfg)\n'
        '{\n'
        '    sample_comm_vi_stop_isp(vi_cfg);  /* stop ISP thread, deregister sensor */\n'
        '    sleep(1);\n'
        '    return sample_comm_vi_start_isp(vi_cfg);  /* re-register, re-init sensor via I2C */\n'
        '}\n'
        '\n'
    )

    # The marker to insert before (the start of sample_comm_vi_start_vi)
    # Find the line "td_s32 sample_comm_vi_start_vi" and insert before it
    old_vi_start_header = 'td_s32 sample_comm_vi_start_vi(const sample_vi_cfg *vi_cfg)\n{'

    new_vi_start_header = (
        'td_s32 sample_comm_vi_restart_sensor_isp(const sample_vi_cfg *vi_cfg)\n'
        '{\n'
        '    sample_comm_vi_stop_isp(vi_cfg);  /* stop ISP thread, deregister sensor */\n'
        '    sleep(1);\n'
        '    return sample_comm_vi_start_isp(vi_cfg);  /* re-register, re-init sensor via I2C */\n'
        '}\n'
        '\n'
        'td_s32 sample_comm_vi_start_vi(const sample_vi_cfg *vi_cfg)\n'
        '{'
    )

    vi_patch_lines = [
        f'old_block = {repr(old_vi_start_header)}',
        f'new_block = {repr(new_vi_start_header)}',
        f'with open({repr(VI_COMMON)}, "r") as f:',
        '    content = f.read()',
        'if old_block in content:',
        '    content = content.replace(old_block, new_block, 1)',
        f'    with open({repr(VI_COMMON)}, "w") as f:',
        '        f.write(content)',
        '    print("VI_COMMON PATCH OK")',
        'else:',
        '    print("VI_COMMON ERROR: pattern not found")',
        '    idx = content.find("td_s32 sample_comm_vi_start_vi")',
        '    if idx >= 0:',
        '        print("Partial match:", repr(content[idx:idx+100]))',
    ]
    vi_patch_script = '\n'.join(vi_patch_lines) + '\n'

    print("\n=== Patching sample_comm_vi.c ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_vi_common.py', 'w') as f:
        f.write(vi_patch_script)
    sftp.close()
    out = run(vm, "python3 /tmp/patch_vi_common.py")
    print(out.strip())

    # Verify vi.c patch
    out = run(vm, f"grep -n 'restart_sensor_isp' {VI_COMMON} | head -5")
    print(f"VI patch verify: {out.strip()}")

    # === PATCH 2: sample_dtof.c - new pre-warm using restart_sensor_isp ===
    # New pre-warm:
    # 1. vi_start #1 (MCLK on, I2C fails OK)
    # 2. sleep(2) for MCLK to stabilize
    # 3. GPIO96 pulse
    # 4. sleep(10) - GS1860 boots on stable MCLK
    # 5. sample_comm_vi_restart_sensor_isp() - ISP only restart, MCLK stays on
    # 6. No vi_stop/vi_start needed for MCLK - just ISP re-init

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
        '    /* GS1860 pre-warm v4: keep MCLK on throughout, only restart ISP */\n'
        '    /* Step 1: enable MCLK (I2C errors expected - GS1860 not yet booted) */\n'
        '    printf("GS1860 pre-warm: enabling MCLK...\\n");\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);  /* MCLK starts, I2C may fail */\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        /* vi_start failed hard (not just I2C) - try cleanup and abort */\n'
        '        goto start_dtof_failed;\n'
        '    }\n'
        '    sleep(2);  /* let MCLK stabilize */\n'
        '\n'
        '    /* Step 2: GPIO96 1->0->1 pulse - GS1860 resets and boots on stable MCLK */\n'
        '    printf("GS1860 pre-warm: GPIO96 reset pulse (MCLK staying on)...\\n");\n'
        '    (void)system("echo 0 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    usleep(100000);  /* 100ms low */\n'
        '    (void)system("echo 1 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    sleep(10);  /* GS1860 needs ~8-9s to boot after reset; MCLK stays on */\n'
        '\n'
        '    /* Step 3: restart only ISP (no vi_stop = MCLK keeps running!) */\n'
        '    /* GS1860 is now at I2C 0x28. Sensor I2C init will succeed this time. */\n'
        '    printf("GS1860 pre-warm: restarting ISP sensor init (MCLK still on)...\\n");\n'
        '    ret = sample_comm_vi_restart_sensor_isp(&vi_cfg[1]);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_comm_vi_stop_vi(&vi_cfg[1]);  /* cleanup VI on ISP restart failure */\n'
        '        goto start_dtof_failed;\n'
        '    }\n'
        '    printf("GS1860 pre-warm done!\\n");'
    )

    dtof_patch_lines = [
        f'old_block = {repr(old_dtof_block)}',
        f'new_block = {repr(new_dtof_block)}',
        f'with open({repr(SRC)}, "r") as f:',
        '    content = f.read()',
        'if old_block in content:',
        '    content = content.replace(old_block, new_block, 1)',
        f'    with open({repr(SRC)}, "w") as f:',
        '        f.write(content)',
        '    print("DTOF PATCH OK")',
        'else:',
        '    print("DTOF ERROR: pattern not found")',
        '    idx = content.find("sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1]")',
        '    if idx >= 0:',
        '        print("Partial:", repr(content[idx:idx+200]))',
    ]
    dtof_patch_script = '\n'.join(dtof_patch_lines) + '\n'

    print("\n=== Patching sample_dtof.c ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_dtof_v4.py', 'w') as f:
        f.write(dtof_patch_script)
    sftp.close()
    out = run(vm, "python3 /tmp/patch_dtof_v4.py")
    print(out.strip())

    # Verify dtof patch
    out = run(vm, f"grep -n 'restart_sensor_isp\\|pre-warm v4\\|MCLK staying on' {SRC} | head -5")
    print(f"DTOF patch verify: {out.strip()}")

    # Rebuild
    print("\n=== Rebuilding ===")
    out = run(vm, f"bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -8'", timeout=120)
    print(out.strip())

    out = run(vm, f"ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof")
    print(f"Binary: {out.strip()}")

    vm.close()

if __name__ == "__main__":
    main()
