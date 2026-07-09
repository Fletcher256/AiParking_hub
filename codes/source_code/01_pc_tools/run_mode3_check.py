#!/usr/bin/env python3
"""Kill background sample_dtof_os08a20, run it manually, capture output."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SERVER_IP = "192.168.137.100"
RUN_SECONDS = 20

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

def stream_run(client, cmd, timeout=60):
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

def main():
    c = connect()

    # Kill background process
    print("=== Killing background sample_dtof_os08a20 ===")
    rc, out = run(c, "kill $(pgrep sample_dtof_os08a20) 2>/dev/null; sleep 1; ps | grep sample_dtof_os08a20")
    print(out)
    c.close()

    time.sleep(2)

    # Run manually with output capture
    print(f"\n=== Running sample_dtof_os08a20 3 manually for {RUN_SECONDS}s ===")
    c2 = connect()
    cmd = (
        f"cd /opt/sample/dtof && "
        f"timeout {RUN_SECONDS} ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1; "
        f"echo EXIT_RC=$?"
    )
    rc, out = stream_run(c2, cmd, timeout=RUN_SECONDS + 15)
    c2.close()

    print("\n=== Analysis ===")
    lines = out.split("\n")
    for line in lines:
        if any(k in line for k in ["success", "fail", "err", "ERR", "FAIL", "vb_set", "mpi_vb",
                                    "DtofInit", "vi_pipe", "venc", "vpss", "stream"]):
            print(f"  >> {line}")

    # Check H.264 file size after run
    time.sleep(1)
    c3 = connect()
    rc, out = run(c3, "ls -la /opt/sample/dtof/stream_chn0.h264 2>/dev/null || echo 'no file'")
    print(f"\nH.264 file: {out.strip()}")
    c3.close()

if __name__ == "__main__":
    main()
