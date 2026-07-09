#!/usr/bin/env python3
"""Build using bash -l to get proper PATH with toolchain."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=300):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Re-apply the fix (it was reverted by previous attempt)
    fix_script = r'''#!/usr/bin/env python3
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
    print("FIX APPLIED")
elif "sns_clk_src = 2;  /* FIX" in content:
    print("FIX ALREADY APPLIED")
else:
    print("ERROR: Pattern not found")
    idx = content.find("bus_id = 4")
    if idx >= 0:
        print(f"Context: {repr(content[idx:idx+200])}")
'''

    # Upload and run fix script
    sftp = c.open_sftp()
    with sftp.file("/tmp/fix.py", 'w') as f:
        f.write(fix_script)
    sftp.close()

    rc, out = run(c, "python3 /tmp/fix.py")
    print(f"Fix: {out.strip()}")

    # Verify fix
    rc, verify = run(c, "grep -n 'sns_clk_src\\|sns_rst_src\\|bus_id' "
                        "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c | head -12")
    print(f"Verify:\n{verify}")

    # Build using bash -l to get proper PATH
    print("=== Building with bash -l ===")
    rc, build = run(c, f"bash -l -c 'cd {DTOF_DIR} && make -j4 2>&1'", timeout=300)
    lines = build.strip().split('\n')
    print(f"Build rc={rc}, {len(lines)} lines")
    # Show last 30 lines
    if len(lines) > 30:
        print("...\n" + '\n'.join(lines[-30:]))
    else:
        print(build)

    if rc == 0:
        # Check binary
        rc, ls = run(c, f"ls -la {DTOF_DIR}/sample_dtof")
        print(f"\nBinary: {ls.strip()}")
        print("\n✅ BUILD SUCCESS")
    else:
        print("\n❌ BUILD FAILED")

    c.close()

if __name__ == "__main__":
    main()
