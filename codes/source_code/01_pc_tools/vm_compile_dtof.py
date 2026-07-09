#!/usr/bin/env python3
"""Compile sample_dtof binary on VM using cross-compiler."""
import paramiko, sys, time

HOST = "192.168.137.100"
USER = "ebaina"
PASS = "ebaina"

def ssh_run(client, cmd, timeout=120):
    chan = client.get_transport().open_session()
    chan.set_combine_stderr(True)
    chan.exec_command(cmd)
    out_chunks = []
    deadline = time.monotonic() + timeout
    while True:
        if chan.recv_ready():
            chunk = chan.recv(4096).decode("utf-8", errors="replace")
            out_chunks.append(chunk)
            print(chunk, end="", flush=True)
        if chan.exit_status_ready():
            while chan.recv_ready():
                chunk = chan.recv(4096).decode("utf-8", errors="replace")
                out_chunks.append(chunk)
                print(chunk, end="", flush=True)
            rc = chan.recv_exit_status()
            return rc, "".join(out_chunks)
        if time.monotonic() > deadline:
            print(f"\n[TIMEOUT after {timeout}s]", flush=True)
            chan.close()
            return -1, "".join(out_chunks)
        time.sleep(0.05)

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=15)
    return client

def main():
    c = connect()
    cmd = (
        "export PATH=/opt/linux/x86-arm/aarch64-mix210-linux/bin:$PATH && "
        "cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && "
        "make 2>&1; echo BUILD_RC=$?"
    )
    print("=== Building sample_dtof ===")
    rc, out = ssh_run(c, cmd, timeout=120)
    c.close()
    if "BUILD_RC=0" in out:
        print("\n[SUCCESS] Build succeeded")
    else:
        print(f"\n[FAIL] Build failed (ssh_rc={rc})")
    return 0 if "BUILD_RC=0" in out else 1

if __name__ == "__main__":
    raise SystemExit(main())
