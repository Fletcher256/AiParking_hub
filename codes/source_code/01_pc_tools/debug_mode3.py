#!/usr/bin/env python3
"""Debug mode 3 VENC issue by running binary in background and checking proc entries."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SERVER_IP = "192.168.137.100"

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client

def run(client, cmd, timeout=15):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def stream_bg(client, cmd, timeout=5):
    """Start a command and read output for 'timeout' seconds, then return what was captured."""
    chan = client.get_transport().open_session()
    chan.set_combine_stderr(True)
    chan.exec_command(cmd)
    out_chunks = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if chan.recv_ready():
            chunk = chan.recv(4096).decode("utf-8", errors="replace")
            out_chunks.append(chunk)
        time.sleep(0.05)
    return chan, "".join(out_chunks)

def main():
    print("=== Starting sample_dtof_os08a20 3 in background ===")
    c1 = connect()
    # Start binary in background via nohup, redirect output to a file
    rc, out = run(c1, "cd /opt/sample/dtof && nohup ./sample_dtof_os08a20 3 %s > /tmp/dtof_debug.log 2>&1 &" % SERVER_IP, timeout=5)
    print(f"Start rc={rc} out={out}")
    c1.close()

    print("Waiting 10s for initialization...")
    time.sleep(10)

    c2 = connect()

    # Check the log output
    rc, out = run(c2, "cat /tmp/dtof_debug.log")
    print("\n=== Binary output so far ===")
    print(out[:3000])  # first 3000 chars

    # Check proc/umap for VPSS status
    print("\n=== /proc/umap/vpss ===")
    rc, out = run(c2, "cat /proc/umap/vpss 2>/dev/null | head -30 || echo 'not found'")
    print(out)

    # Check proc/umap for VENC status
    print("\n=== /proc/umap/venc ===")
    rc, out = run(c2, "cat /proc/umap/venc 2>/dev/null | head -30 || echo 'not found'")
    print(out)

    # Check proc/umap for VI status
    print("\n=== /proc/umap/vi ===")
    rc, out = run(c2, "cat /proc/umap/vi 2>/dev/null | head -30 || echo 'not found'")
    print(out)

    # Check VB pool status
    print("\n=== /proc/umap/vb ===")
    rc, out = run(c2, "cat /proc/umap/vb 2>/dev/null | head -40 || echo 'not found'")
    print(out)

    # Check sys bind table
    print("\n=== /proc/umap/sys bind ===")
    rc, out = run(c2, "cat /proc/umap/sys 2>/dev/null | grep -A5 'bind\\|VPSS\\|VENC' | head -30 || echo 'not found'")
    print(out)

    # Check /proc/umap directory
    print("\n=== /proc/umap contents ===")
    rc, out = run(c2, "ls /proc/umap/ 2>/dev/null || echo 'no umap'")
    print(out)

    c2.close()

    print("\n=== Cleaning up ===")
    c3 = connect()
    run(c3, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null")
    c3.close()

if __name__ == "__main__":
    main()
