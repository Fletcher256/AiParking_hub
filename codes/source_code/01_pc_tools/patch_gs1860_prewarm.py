#!/usr/bin/env python3
"""
Patch sample_dtof.c to add GS1860 MCLK pre-warm and GPIO96 re-pulse retry.

Root cause: GS1860 needs MCLK running before it can boot and respond to I2C.
MCLK is only enabled when sample_comm_vi_start_vi is called.
Fix: call vi_start (enables MCLK, I2C may fail) → wait → pulse GPIO96 →
     wait → vi_stop → vi_start again (sensor now responds to I2C).
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

    # 1. Backup
    print("=== Backup sample_dtof.c ===")
    out = run(vm, f"cp {SRC} {SRC}.bak_prewarm && echo 'backed up'")
    print(out.strip())

    # 2. Show the current GS1860 VI start block in sample_dtof_dtof_and_rgb
    print("\n=== Current GS1860 VI start block ===")
    out = run(vm, f"grep -n 'gs1860_read_ini\\|sample_dtof_get_one_dtof\\|sample_comm_vi_start_vi.*1.*\\|dtof_init\\|vi_bayerdump\\|start_dtof_failed' {SRC} | head -20")
    print(out.strip())

    # 3. Find the exact line to patch
    # The patch point: the line with "ret = sample_comm_vi_start_vi(&vi_cfg[1]);"
    # in sample_dtof_dtof_and_rgb (not sample_dtof_one_dtof_sensor)
    print("\n=== Finding patch location ===")
    out = run(vm, f"grep -n 'sample_comm_vi_start_vi' {SRC}")
    print(out.strip())

    # 4. Read lines around the GS1860 vi_start in dtof_and_rgb
    # It's the second occurrence of sample_comm_vi_start_vi (in dtof_and_rgb)
    # Find line number
    lines = out.strip().split('\n')
    vi_start_lines = [l for l in lines if 'sample_comm_vi_start_vi' in l]
    print(f"\nvi_start occurrences: {vi_start_lines}")

    # The one in dtof_and_rgb has vi_cfg[1] (not vi_cfg[0])
    target_line = None
    for l in vi_start_lines:
        if 'vi_cfg[1]' in l or 'vi_cfg\\[1\\]' in l:
            target_line = int(l.split(':')[0].strip())
            break

    if target_line is None:
        # Find by context - look for the one after gs1860_read_ini_file
        out2 = run(vm, f"grep -n 'vi_cfg\\[1\\]' {SRC} | head -10")
        print("vi_cfg[1] lines:", out2.strip())

    print(f"\nTarget vi_start line: {target_line}")

    # 5. Apply the patch using Python script on VM
    patch_script = f'''
import re

with open('{SRC}', 'r') as f:
    content = f.read()

# Find the block to replace in sample_dtof_dtof_and_rgb
# The pattern: the vi_cfg[1] vi_start call followed by error check
old_block = """    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);
    ret = sample_comm_vi_start_vi(&vi_cfg[1]);
    if (ret != TD_SUCCESS) {{
        goto start_dtof_failed;
    }}"""

new_block = """    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);

    /* Pre-warm GS1860: first call enables MCLK (I2C errors expected - sensor still booting) */
    printf("GS1860 pre-warm: enabling MCLK...\\n");
    (void)sample_comm_vi_start_vi(&vi_cfg[1]);   /* MCLK starts, I2C may fail */
    sleep(6);  /* wait for GS1860 to boot on MCLK */

    /* Pulse GPIO96 to reset GS1860 (now has MCLK, will respond after reset) */
    printf("GS1860 pre-warm: pulsing GPIO96 reset...\\n");
    (void)system("echo 0 > /sys/class/gpio/gpio96/value 2>/dev/null");
    usleep(100000);  /* 100ms reset pulse */
    (void)system("echo 1 > /sys/class/gpio/gpio96/value 2>/dev/null");
    sleep(3);  /* wait for GS1860 to re-init */

    /* Stop partial VI, then restart properly */
    sample_comm_vi_stop_vi(&vi_cfg[1]);
    sleep(1);

    printf("GS1860 pre-warm done, starting real VI init...\\n");
    ret = sample_comm_vi_start_vi(&vi_cfg[1]);   /* real init - GS1860 responds to I2C now */
    if (ret != TD_SUCCESS) {{
        goto start_dtof_failed;
    }}"""

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open('{SRC}', 'w') as f:
        f.write(content)
    print("PATCH APPLIED SUCCESSFULLY")
else:
    print("ERROR: Pattern not found in file")
    # Show what we're looking for:
    print("Looking for:")
    print(repr(old_block[:200]))
    # Find closest match
    idx = content.find("sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1]")
    if idx >= 0:
        print("Found partial match at:", idx)
        print("Context:", repr(content[idx:idx+300]))
'''

    # Upload and run patch script
    print("\n=== Uploading patch script ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_gs1860.py', 'w') as f:
        f.write(patch_script)
    sftp.close()

    out = run(vm, "python3 /tmp/patch_gs1860.py", timeout=30)
    print(out.strip())

    # 6. Verify patch
    print("\n=== Verify patch (show patched lines) ===")
    out = run(vm, f"grep -n 'pre-warm\\|gpio96\\|usleep\\|printf.*GS1860' {SRC} | head -20")
    print(out.strip())

    # 7. Show the patched section
    print("\n=== Patched section ===")
    out = run(vm, f"grep -n 'get_one_dtof_sensor_vi_cfg' {SRC}")
    if out.strip():
        line = int(out.strip().split('\n')[0].split(':')[0])
        out2 = run(vm, f"sed -n '{line},{line+40}p' {SRC}")
        print(out2.strip())

    vm.close()

if __name__ == "__main__":
    main()
