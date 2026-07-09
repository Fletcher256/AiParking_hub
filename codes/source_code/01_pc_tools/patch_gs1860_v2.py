#!/usr/bin/env python3
"""
Patch sample_dtof.c to add GS1860 MCLK pre-warm.
v2: Fixes \n escaping issue in printf strings.
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

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect()

    # Restore from backup first
    print("=== Restoring backup ===")
    out = run(vm, f"cp {SRC}.bak_prewarm {SRC} && echo 'restored'")
    print(out.strip())

    # Build the patch script carefully - use repr() to avoid escaping issues
    # The C code we want to insert as new_block
    new_c_code = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '\n'
        '    /* Pre-warm GS1860: first call enables MCLK (I2C errors expected - sensor booting) */\n'
        '    printf("GS1860 pre-warm: enabling MCLK...\\n");\n'
        '    (void)sample_comm_vi_start_vi(&vi_cfg[1]);   /* MCLK starts, I2C may fail */\n'
        '    sleep(6);  /* wait for GS1860 to boot on MCLK */\n'
        '\n'
        '    /* Pulse GPIO96 to reset GS1860 (now has MCLK, will respond after reset) */\n'
        '    printf("GS1860 pre-warm: pulsing GPIO96 reset...\\n");\n'
        '    (void)system("echo 0 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    usleep(100000);  /* 100ms reset pulse */\n'
        '    (void)system("echo 1 > /sys/class/gpio/gpio96/value 2>/dev/null");\n'
        '    sleep(3);  /* wait for GS1860 to re-init */\n'
        '\n'
        '    /* Stop partial VI, then restart properly */\n'
        '    sample_comm_vi_stop_vi(&vi_cfg[1]);\n'
        '    sleep(1);\n'
        '\n'
        '    printf("GS1860 pre-warm done, starting real VI init...\\n");\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);   /* real init - GS1860 ready */\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }'
    )

    old_c_code = (
        '    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);\n'
        '    ret = sample_comm_vi_start_vi(&vi_cfg[1]);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        goto start_dtof_failed;\n'
        '    }'
    )

    # Write patch script using repr() so all special chars are escaped
    patch_lines = [
        'import sys',
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
        '        print("Partial match found:", repr(content[idx:idx+200]))',
    ]
    patch_script = '\n'.join(patch_lines) + '\n'

    # Upload patch script
    print("\n=== Uploading patch script ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_gs1860_v2.py', 'w') as f:
        f.write(patch_script)
    sftp.close()

    # Show what was uploaded
    out = run(vm, "cat /tmp/patch_gs1860_v2.py")
    print(out)

    # Run patch
    print("=== Running patch ===")
    out = run(vm, "python3 /tmp/patch_gs1860_v2.py")
    print(out.strip())

    # Verify - check lines look correct
    print("\n=== Verify (show patched block) ===")
    out = run(vm, f"grep -n 'pre-warm\\|printf.*GS1860\\|gpio96\\|usleep' {SRC}")
    print(out.strip())

    # Show the actual C lines with printf
    print("\n=== Check printf lines for \\n ===")
    out = run(vm, f"grep 'printf.*GS1860' {SRC} | cat -A | head -5")
    print(out.strip())

    # Quick compile test
    print("\n=== Quick syntax check ===")
    out = run(vm, f"bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -5'", timeout=120)
    print(out.strip())

    vm.close()

if __name__ == "__main__":
    main()
