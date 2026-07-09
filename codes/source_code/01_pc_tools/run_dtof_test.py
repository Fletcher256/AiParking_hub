#!/usr/bin/env python3
"""
Load KO modules and run sample_dtof_os08a20 mode 3 on the board.
Uses long timeouts so SSH doesn't drop mid-script.
"""
import paramiko, sys, time

HOST = "192.168.137.2"
USER = "root"
PASS = "ebaina"
SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.137.100"
RUN_SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 30


def ssh_run(client, cmd, timeout=180):
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
            # drain remaining
            while chan.recv_ready():
                chunk = chan.recv(4096).decode("utf-8", errors="replace")
                out_chunks.append(chunk)
                print(chunk, end="", flush=True)
            rc = chan.recv_exit_status()
            return rc, "".join(out_chunks)
        if time.monotonic() > deadline:
            print(f"\n[TIMEOUT after {timeout}s]")
            chan.close()
            return -1, "".join(out_chunks)
        time.sleep(0.1)


def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client


def main():
    print("=== Step 1: Load KO modules ===")
    c = connect()
    rc, _ = ssh_run(c, "cd /opt/ko && sh load_ss928v100 -a -sensor0 os08a20", timeout=120)
    c.close()
    print(f"\n[load_ss928v100 rc={rc}]")

    print("\n=== Step 2: Run dtof_init.sh ===")
    c = connect()
    rc, _ = ssh_run(c, "sh /opt/ko/dtof_init.sh", timeout=30)
    c.close()
    print(f"\n[dtof_init rc={rc}]")

    print(f"\n=== Step 3: Run sample_dtof_os08a20 mode=3 for {RUN_SECONDS}s ===")
    c = connect()
    # Run in background with timeout wrapper
    cmd = (
        f"cd /opt/sample/dtof && "
        f"timeout {RUN_SECONDS} ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1; echo EXIT_CODE=$?"
    )
    rc, out = ssh_run(c, cmd, timeout=RUN_SECONDS + 30)
    c.close()
    print(f"\n[sample_dtof rc={rc}]")

    if "DtofInit success" in out:
        print("\n[OK] DtofInit success - I2C working")
    if "vi_pipe 2 frame err" in out:
        print("\n[FAIL] Still getting vi_pipe 2 frame err")
    elif "DtofInit success" in out:
        print("\n[LIKELY OK] No frame errors detected!")


if __name__ == "__main__":
    main()
