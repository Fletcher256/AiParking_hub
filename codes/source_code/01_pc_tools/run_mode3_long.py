#!/usr/bin/env python3
"""Run mode 3 for 60 seconds and look for VENC frames + VB errors."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
SERVER_IP = "192.168.137.100"
RUN_SECONDS = 60

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client

def stream_run(client, cmd, timeout=90):
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

def run(client, cmd, timeout=15):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    print(f"=== Running mode 3 for {RUN_SECONDS}s, streaming output ===")
    c = connect()
    cmd = (
        f"cd /opt/sample/dtof && "
        f"timeout {RUN_SECONDS} ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1; "
        f"echo EXIT_RC=$?"
    )
    rc, out = stream_run(c, cmd, timeout=RUN_SECONDS + 20)
    c.close()

    print("\n=== Summary ===")
    venc_timeout_count = out.count("get venc stream time out")
    venc_frame_count = out.count("venc_write_frame") + out.count("stream_chn")
    frame_err_count = out.count("vi_pipe 2 frame err")
    vb_err = "vb_set_conf" in out or "mpi_vb_set_cfg" in out
    dtof_ok = "DtofInit success" in out
    os08_ok = "os08a20" in out and "init success" in out

    print(f"OS08A20 init: {'OK' if os08_ok else 'FAIL'}")
    print(f"dToF init: {'OK' if dtof_ok else 'FAIL'}")
    print(f"VENC timeouts: {venc_timeout_count}")
    print(f"vi_pipe 2 frame errors: {frame_err_count}")
    print(f"VB errors: {'YES' if vb_err else 'NO'}")

    # Check H.264 file
    c2 = connect()
    rc2, finfo = run(c2, "ls -la /opt/sample/dtof/stream_chn0.h264 2>/dev/null")
    print(f"\nH.264 file: {finfo.strip()}")
    # Check if bind error messages appear
    rc3, bstat = run(c2, "dmesg | grep -i 'bind\\|vpss\\|venc' 2>/dev/null | tail -10")
    print(f"\ndmesg vpss/venc:\n{bstat}")
    c2.close()

if __name__ == "__main__":
    main()
