#!/usr/bin/env python3
"""Build the dtof binary on VM after applying the fix."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
DTOF_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=180):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Check what's in the dtof Makefile
    print("=== dtof/Makefile head ===")
    rc, mf = run(c, f"head -30 {DTOF_DIR}/Makefile")
    print(mf)

    # Check what output files exist
    print("\n=== Current binary (before rebuild) ===")
    rc, ls = run(c, f"ls -la {DTOF_DIR}/ | grep sample")
    print(ls.strip())

    # Build
    print("\n=== Building (make -j4) ===")
    rc, build = run(c, f"cd {DTOF_DIR} && make -j4 2>&1", timeout=300)
    print(f"rc={rc}")
    print(build[-3000:])  # last 3000 chars

    # Check output
    print("\n=== Binary after build ===")
    rc, ls2 = run(c, f"ls -la {DTOF_DIR}/ | grep sample")
    print(ls2.strip())

    c.close()

if __name__ == "__main__":
    main()
