#!/usr/bin/env python3
"""Reboot the board and wait for it to come back up, then verify."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def try_connect(timeout=8):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                       timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
        return client
    except Exception:
        return None

def run(client, cmd, timeout=20):
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
            chan.close()
            return -1, "".join(out_chunks)
        time.sleep(0.05)

def main():
    # Step 1: Send reboot command
    c = try_connect()
    if not c:
        print("ERROR: Board not reachable")
        sys.exit(1)

    print("=== Sending reboot command ===")
    try:
        c.exec_command("reboot", timeout=5)
    except Exception:
        pass
    c.close()

    # Step 2: Wait for board to go down
    print("Waiting for board to go down...")
    time.sleep(10)
    for i in range(20):
        c2 = try_connect(timeout=3)
        if c2:
            c2.close()
            print(f"  Still up... ({i+1})")
            time.sleep(3)
        else:
            print("  Board is down, waiting for it to come back...")
            break

    # Step 3: Wait for board to come back up
    print("Waiting for board to come back up (up to 3 minutes)...")
    deadline = time.monotonic() + 180
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        c3 = try_connect(timeout=5)
        if c3:
            print(f"  Board back up after {attempt} polls!")
            break
        print(f"  Poll {attempt}: not up yet...")
        time.sleep(5)
    else:
        print("ERROR: Board did not come back within 3 minutes")
        sys.exit(1)

    # Step 4: Wait for S90autorun to finish (KO load + dtof_init + binary start)
    print("\n=== Board is up. Waiting 30s for S90autorun to complete ===")
    time.sleep(30)

    # Step 5: Verify
    c4 = try_connect()
    if not c4:
        print("ERROR: Lost connection after wait")
        sys.exit(1)

    print("\n=== Verification ===")

    rc, out = run(c4, "uptime")
    print(f"Uptime: {out.strip()}")

    rc, out = run(c4, "ps | grep sample_dtof_os08a20")
    print(f"\nProcess check:\n{out}")

    rc, out = run(c4, "dmesg | grep -E 'vi_pipe 2 frame err|vb_set_conf|mpi_vb_set_cfg|DtofInit|gs1860|os08a20' 2>&1")
    print(f"\ndmesg relevant:\n{out}")

    # Check if process is actually running
    if "sample_dtof_os08a20" in out or "sample_dtof_os08a20" in "":
        pass
    rc2, ps_out = run(c4, "ps")
    if "sample_dtof_os08a20" in ps_out:
        print("\n[SUCCESS] sample_dtof_os08a20 is running!")
    else:
        print("\n[WARN] sample_dtof_os08a20 not in ps - checking if it crashed...")
        # Try running it manually with a short timeout
        print("\n--- Running sample_dtof_os08a20 manually for 15s ---")
        rc, out = stream_run(c4,
            "cd /opt/sample/dtof && timeout 15 ./sample_dtof_os08a20 3 192.168.137.100 2>&1; echo MANUAL_RC=$?",
            timeout=20)
        print(f"\nManual run result: {out[-500:] if len(out) > 500 else out}")

    c4.close()

if __name__ == "__main__":
    main()
