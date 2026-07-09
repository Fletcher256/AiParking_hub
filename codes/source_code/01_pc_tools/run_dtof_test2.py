#!/usr/bin/env python3
"""
Load KO modules (insmod only, no rmmod) and run sample_dtof_os08a20 mode 3.
Use this on a freshly booted board where no KO modules are loaded yet.
"""
import paramiko, sys, time

HOST = "192.168.137.2"
USER = "root"
PASS = "ebaina"
SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.137.100"
RUN_SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 40


def ssh_run_streaming(client, cmd, timeout=180):
    """Run command and stream output in real time."""
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
    client.connect(HOST, username=USER, password=PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client


def main():
    print("=== Step 1: Load KO (insmod only, no rmmod) ===")
    c = connect()
    # Without -a flag: only insmod, no rmmod — safe on fresh boot
    rc, out = ssh_run_streaming(c, "cd /opt/ko && sh load_ss928v100 -sensor0 os08a20 2>&1; echo KO_RC=$?", timeout=90)
    c.close()
    print(f"\n[load KO done rc={rc}]")

    if "KO_RC=0" not in out and "already" not in out.lower():
        print("WARNING: KO load may have issues, continuing anyway...")

    print("\n=== Step 2: Run dtof_init.sh ===")
    c = connect()
    rc, _ = ssh_run_streaming(c, "sh /opt/ko/dtof_init.sh 2>&1; echo DTOF_INIT_RC=$?", timeout=20)
    c.close()

    print(f"\n=== Step 3: Run sample_dtof_os08a20 mode=3 for {RUN_SECONDS}s ===")
    c = connect()
    cmd = (
        f"cd /opt/sample/dtof && "
        f"timeout {RUN_SECONDS} ./sample_dtof_os08a20 3 {SERVER_IP} 2>&1; echo SAMPLE_RC=$?"
    )
    rc, out = ssh_run_streaming(c, cmd, timeout=RUN_SECONDS + 30)
    c.close()

    print("\n=== Analysis ===")
    if "DtofInit success" in out:
        print("[OK] DtofInit success - GS1860 I2C OK")
    else:
        print("[FAIL] DtofInit not found in output")

    frame_errs = out.count("vi_pipe 2 frame err")
    if frame_errs == 0 and "DtofInit success" in out:
        print("[SUCCESS] No frame errors - HEIGHT fix worked!")
    elif frame_errs > 0:
        print(f"[FAIL] {frame_errs} frame errors still occurring")

    if "vb_set_conf failed" in out:
        print("[FAIL] VB pool init failed - may need full KO reload")


if __name__ == "__main__":
    main()
