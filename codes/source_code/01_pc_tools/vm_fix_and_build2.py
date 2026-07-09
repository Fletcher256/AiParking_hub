#!/usr/bin/env python3
"""Apply the GS1860 sns_rst_src fix and rebuild. Upload fix script to VM via SFTP."""
import paramiko, time, io

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_C   = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

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

def upload_script(c, remote_path, content):
    sftp = c.open_sftp()
    with sftp.file(remote_path, 'w') as f:
        f.write(content)
    sftp.close()

def main():
    c = connect()

    # 1. Find Makefile
    print("=== Finding Makefile ===")
    rc, out = run(c, "find /home/ebaina/ZZIP/SS928V100_dtof_build_source -name 'Makefile' -maxdepth 3 2>/dev/null | head -10")
    print(out.strip())

    # 2. Upload a Python fix script
    fix_script = r'''#!/usr/bin/env python3
"""Apply fix: change GS1860 sns_rst_src from 0 to 2 in sample_dtof.c"""
DTOF_C = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

with open(DTOF_C, "r") as f:
    content = f.read()

old = (
    "vi_cfg->sns_info.bus_id = 4; /* i2c4 */\n"
    "        vi_cfg->sns_info.sns_clk_src = 0;\n"
    "        vi_cfg->sns_info.sns_rst_src = 0;"
)
new = (
    "vi_cfg->sns_info.bus_id = 4; /* i2c4 */\n"
    "        vi_cfg->sns_info.sns_clk_src = 2;  /* FIX: avoid clk conflict with OS08A20 */\n"
    "        vi_cfg->sns_info.sns_rst_src = 2;  /* FIX: avoid rst conflict with OS08A20 */"
)

if old in content:
    content = content.replace(old, new, 1)
    with open(DTOF_C, "w") as f:
        f.write(content)
    print("SUCCESS: Applied fix")
else:
    print("ERROR: Pattern not found")
    # Debug: show context
    idx = content.find("bus_id = 4")
    if idx >= 0:
        print(f"Context: {repr(content[idx:idx+200])}")
    else:
        print("bus_id=4 not found either")
'''

    print("\n=== Uploading fix script to VM ===")
    upload_script(c, "/tmp/apply_fix.py", fix_script)
    rc, out = run(c, "python3 /tmp/apply_fix.py")
    print(f"Fix result: {out.strip()}")

    # 3. Verify fix was applied
    print("\n=== Verify fix applied ===")
    rc, ctx = run(c, f"grep -n 'sns_clk_src\\|sns_rst_src\\|bus_id' {DTOF_C} | head -20")
    print(ctx)

    # 4. Find and run make
    print("\n=== Finding build system ===")
    rc, makefiles = run(c, "find /home/ebaina/ZZIP/SS928V100_dtof_build_source -name 'Makefile' 2>/dev/null")
    print(makefiles.strip())

    # Try to find the build directory with a Makefile that builds sample_dtof
    rc, out2 = run(c, "find /home/ebaina/ZZIP/SS928V100_dtof_build_source -name 'Makefile' -exec grep -l 'sample_dtof\\|dtof' {} \\; 2>/dev/null | head -5")
    print(f"\nMakefiles mentioning dtof:\n{out2.strip()}")

    # 5. Try the build script if available
    print("\n=== Looking for build scripts ===")
    rc, scripts = run(c, "find /home/ebaina/ZZIP/SS928V100_dtof_build_source -name '*.sh' -maxdepth 2 2>/dev/null | head -10")
    print(scripts.strip())
    rc, scripts2 = run(c, "ls /home/ebaina/ZZIP/SS928V100_dtof_build_source/ 2>/dev/null")
    print(f"\nTop level:\n{scripts2.strip()}")

    c.close()

if __name__ == "__main__":
    main()
