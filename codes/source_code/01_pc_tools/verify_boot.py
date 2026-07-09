#!/usr/bin/env python3
"""Wait for board to come up and verify sample_dtof_os08a20 mode 3 is running."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def try_connect(timeout=10):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                       timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
        return client
    except Exception as e:
        return None

def run(client, cmd, timeout=20):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def wait_for_board(max_wait=120):
    print("Waiting for board to become reachable...")
    deadline = time.monotonic() + max_wait
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        c = try_connect(timeout=5)
        if c:
            print(f"  Board reachable after {attempt} attempts")
            return c
        print(f"  Attempt {attempt}: not reachable yet...")
        time.sleep(5)
    print("ERROR: Board did not come up within timeout")
    return None

def main():
    c = try_connect(timeout=5)
    if not c:
        print("Board not currently reachable. Waiting for reboot...")
        c = wait_for_board(max_wait=180)
        if not c:
            sys.exit(1)

    print("\n=== Board is up. Checking S90autorun output (waiting 15s for init) ===")
    time.sleep(15)

    # Check if sample_dtof_os08a20 is running
    rc, out = run(c, "ps | grep sample_dtof")
    print("--- Running processes ---")
    print(out)

    # Check dmesg for any kernel errors
    rc, out = run(c, "dmesg | grep -i 'err\\|fail\\|vi_pipe 2' | tail -20")
    print("--- dmesg errors ---")
    print(out)

    # Check if sample_dtof_os08a20 produced any output (via logfile if any)
    rc, out = run(c, "ls -la /opt/sample/dtof/sample_dtof_os08a20")
    print("--- Binary info ---")
    print(out)

    # Check current autorun content
    rc, out = run(c, "cat /etc/init.d/S90autorun")
    print("--- S90autorun ---")
    print(out)

    c.close()

if __name__ == "__main__":
    main()
