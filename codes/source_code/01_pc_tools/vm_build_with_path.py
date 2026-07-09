#!/usr/bin/env python3
"""Build dtof binary with correct toolchain path."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"
TOOLCHAIN = "/opt/linux/x86-arm/aarch64-mix210-linux/host_bin"

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

    # Build with toolchain in PATH
    print("=== Building sample_dtof with fixed sns_rst_src ===")
    build_cmd = (
        f"export PATH={TOOLCHAIN}:$PATH && "
        f"cd {DTOF_DIR} && "
        f"make -j4 2>&1"
    )
    rc, out = run(c, build_cmd, timeout=300)
    print(f"Build rc={rc}")
    # Show last 50 lines
    lines = out.strip().split('\n')
    if len(lines) > 50:
        print(f"... (showing last 50 of {len(lines)} lines) ...")
        print('\n'.join(lines[-50:]))
    else:
        print(out)

    if rc == 0:
        print("\n=== Build SUCCESS - checking binary ===")
        rc, ls = run(c, f"ls -la {DTOF_DIR}/sample_dtof")
        print(ls.strip())

        # Also verify the compiled binary contains the fix
        # (check if it's newer than the backup)
        rc, chk = run(c, f"ls -la --time-style='+%Y-%m-%d %H:%M:%S' {DTOF_DIR}/sample_dtof "
                        f"{DTOF_DIR}/sample_dtof.c.bak_rs0")
        print(f"\nTimestamp comparison:\n{chk.strip()}")
    else:
        print("\nBuild FAILED - reverting fix")
        rc, rv = run(c, f"cp {DTOF_DIR}/sample_dtof.c.bak_rs0 {DTOF_DIR}/sample_dtof.c && echo 'Reverted'")
        print(rv.strip())

    c.close()

if __name__ == "__main__":
    main()
