#!/usr/bin/env python3
"""
Patch sample_dtof.c - GS1860 pre-warm v3.
Key fix: sleep(10) after GPIO96 pulse (empirically: GS1860 needs ~8s to boot after reset).
Also: simplified sequence - no sleep(6) before GPIO96 pulse.
"""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

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

    # Restore from backup
    print("=== Restoring backup ===")
    out = run(vm, f"cp {SRC}.bak_prewarm {SRC} && echo 'restored'")
    print(out.strip())

    # The C code blocks (as Python strings, properly escaped)
    old_c_code = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }'
    )

    # New sequence:
    # 1. vi_start #1 (MCLK on, 92 I2C errors expected - OK)
    # 2. sleep(1) - MCLK stabilize
    # 3. GPIO96 1→0→1 - GS1860 resets and begins booting on MCLK
    # 4. sleep(10) - EMPIRICALLY: GS1860 needs ~8s to fully boot after reset
    # 5. vi_stop - MCLK off briefly; GS1860 MAINTAINS I2C state (tested: stays 20+ sec)
    # 6. sleep(1)
    # 7. vi_start #2 - MCLK on, I2C init runs, GS1860 responds → SUCCESS
    new_c_code = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '\n'
        '    /* Pre-warm GS1860: enable MCLK first (I2C errors expected - sensor not yet booted) */\n'
        '    printf("GS1860 pre-warm: enabling MCLK...\\n");\n'
        '    (void)sample_comm_vi_start_vi(&vi_cfg[1]);  /* MCLK starts, I2C may fail */\n'
        '    sleep(1);  /* brief wait for MCLK to stabilize */\n'
        '\n'
        '    /* Pulse GPIO96 to reset GS1860 - it will boot on the now-stable MCLK */\n'
        '    printf("GS1860 pre-warm: pulsing GPIO96 reset...\\n");\n'
        '    (void)system("echo 0 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    usleep(100000);  /* 100ms low pulse */\n'
        '    (void)system("echo 1 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    sleep(10);  /* GS1860 needs ~8-9s to boot after GPIO reset - wait fully */\n'
        '\n'
        '    /* GS1860 now at I2C 0x28. Stop VI briefly, restart for proper sensor init. */\n'
        '    /* GS1860 maintains I2C state for 20+ seconds without MCLK (empirically tested) */\n'
        '    sample_comm_vi_stop_vi(&vi_cfg[1]);\n'
        '    sleep(1);\n'
        '\n'
        '    printf("GS1860 pre-warm done, starting real VI init...\\n");\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);  /* real init - GS1860 now responds */\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }'
    )

    # Build patch script using repr() to avoid escaping issues
    patch_lines = [
        f'old_block = {repr(old_c_code)}',
        f'new_block = {repr(new_c_code)}',
        f'with open({repr(SRC)}, "r") as f:',
        '    content = f.read()',
        'if old_block in content:',
        '    content = content.replace(old_block, new_block, 1)',
        f'    with open({repr(SRC)}, "w") as f:',
        '        f.write(content)',
        '    print("PATCH APPLIED SUCCESSFULLY")',
        'else:',
        '    print("ERROR: Pattern not found")',
        '    idx = content.find("sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1]")',
        '    if idx >= 0:',
        '        print("Partial:", repr(content[idx:idx+300]))',
    ]
    patch_script = '\n'.join(patch_lines) + '\n'

    # Upload patch script
    print("=== Uploading patch script v3 ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_gs1860_v3.py', 'w') as f:
        f.write(patch_script)
    sftp.close()

    # Run patch
    print("=== Running patch ===")
    out = run(vm, "python3 /tmp/patch_gs1860_v3.py")
    print(out.strip())

    # Verify
    print("\n=== Verify patch ===")
    out = run(vm, f"grep -n 'pre-warm\\|gpio96\\|sleep(10)\\|sleep(1)\\|printf.*GS1860' {SRC} | head -15")
    print(out.strip())

    # Rebuild
    print("\n=== Rebuilding ===")
    out = run(vm, f"bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -5'", timeout=120)
    print(out.strip())

    # Check binary
    out = run(vm, f"ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof 2>/dev/null")
    print(f"Binary: {out.strip()}")

    vm.close()

if __name__ == "__main__":
    main()
