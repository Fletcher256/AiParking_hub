#!/usr/bin/env python3
"""Apply the GS1860 sns_rst_src fix and rebuild the binary on VM."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_C   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
BUILD_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=120):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # 1. Backup original file
    print("=== Backing up sample_dtof.c ===")
    rc, out = run(c, f"cp {DTOF_C} {DTOF_C}.bak_rs0 && echo 'Backup OK'")
    print(out.strip())

    # 2. Verify the exact lines to change (sensor_num==2 block)
    print("\n=== Verifying lines 252-253 (sns_clk/rst for sensor_num==2) ===")
    rc, ctx = run(c, f"sed -n '248,260p' {DTOF_C}")
    print(ctx)

    # 3. Apply the fix: change sns_clk_src=0 and sns_rst_src=0 at lines 252,253
    # These are inside the sensor_num==2 block (after the bus_id=4 line)
    # We need to target ONLY these two lines, not the ones in get_one_sensor_vi_cfg
    # The unique context: bus_id=4 (i2c4) precedes these lines in sensor_num==2 block
    print("\n=== Applying fix: sns_clk_src=0->2, sns_rst_src=0->2 for GS1860 (sensor_num==2) ===")

    # Use Python to do a surgical replacement - only change the sensor_num==2 block
    fix_script = '''
import re

with open("{dtof_c}", "r") as f:
    content = f.read()

# Find the sensor_num==2 block in get_one_dtof_sensor_vi_cfg
# Pattern: after 'bus_id = 4' (i2c4 = GS1860 bus), change sns_clk_src=0 and sns_rst_src=0
# We look for the specific pattern: bus_id = 4 followed by sns_clk_src = 0
old_pattern = (
    'vi_cfg->sns_info.bus_id = 4; /* i2c4 */\\n'
    '        vi_cfg->sns_info.sns_clk_src = 0;\\n'
    '        vi_cfg->sns_info.sns_rst_src = 0;'
)
new_pattern = (
    'vi_cfg->sns_info.bus_id = 4; /* i2c4 */\\n'
    '        vi_cfg->sns_info.sns_clk_src = 2;  /* FIX: avoid conflict with OS08A20 (clk_src=0) */\\n'
    '        vi_cfg->sns_info.sns_rst_src = 2;  /* FIX: avoid resetting OS08A20 (rst_src=0) */'
)

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern, 1)
    with open("{dtof_c}", "w") as f:
        f.write(content)
    print("FIX APPLIED: sns_clk_src and sns_rst_src changed to 2 for sensor_num==2 (GS1860)")
else:
    print("ERROR: Pattern not found! Check the source file.")
    # Print context around bus_id=4
    idx = content.find("bus_id = 4")
    if idx >= 0:
        print("Context around bus_id=4:", repr(content[idx-20:idx+200]))
'''.format(dtof_c=DTOF_C)

    rc, out = run(c, f"python3 -c '{fix_script}'")
    print(out.strip())

    # 4. Verify the fix was applied
    print("\n=== Verifying fix ===")
    rc, ctx2 = run(c, f"sed -n '248,262p' {DTOF_C}")
    print(ctx2)

    # 5. Also verify OS08A20 config is unchanged (sns_rst_src=0 for sensor_num==0)
    print("\n=== Verifying OS08A20 config unchanged (sensor_num==0, rst_src should be 0) ===")
    rc, check = run(c, f"grep -n 'sns_rst_src\\|sns_clk_src' {DTOF_C}")
    print(check)

    # 6. Rebuild
    print("\n=== Rebuilding binary ===")
    rc, build_out = run(c, f"cd {BUILD_DIR} && make -j4 2>&1 | tail -20", timeout=180)
    print(f"Build rc={rc}")
    print(build_out)

    if rc != 0:
        print("\nBuild FAILED. Reverting...")
        run(c, f"cp {DTOF_C}.bak_rs0 {DTOF_C}")
        c.close()
        return

    # 7. Check binary was produced
    print("\n=== Binary check ===")
    rc, ls = run(c, f"ls -la {BUILD_DIR}/out/sample_dtof_os08a20 2>/dev/null || "
                    f"find {BUILD_DIR} -name 'sample_dtof_os08a20' -newer {DTOF_C}.bak_rs0 2>/dev/null | head -3")
    print(ls.strip())

    c.close()

if __name__ == "__main__":
    main()
