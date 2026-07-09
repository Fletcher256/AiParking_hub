#!/usr/bin/env python3
"""Deploy new binary from VM to board and test mode 3."""
import paramiko, time

VM_HOST   = "192.168.137.100"
VM_USER   = "ebaina"
VM_PASS   = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_BINARY  = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
BOARD_DEST = "/opt/sample/dtof/sample_dtof_os08a20"

def connect_vm():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def connect_board(timeout=30):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=timeout)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def wait_board(timeout_s=120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            c = connect_board(timeout=8)
            c.close()
            return True
        except Exception:
            time.sleep(3)
    return False

def main():
    # 1. Download binary from VM
    print("=== Downloading new binary from VM ===")
    vm = connect_vm()
    sftp_vm = vm.open_sftp()
    binary_data = sftp_vm.open(VM_BINARY, 'rb').read()
    sftp_vm.close()
    vm.close()
    print(f"Downloaded: {len(binary_data)} bytes")

    # 2. Kill current binary on board cleanly (SIGTERM)
    print("\n=== Killing current binary on board (SIGTERM) ===")
    board = connect_board()
    run(board, "pkill -15 -f sample_dtof_os08a20 2>/dev/null")
    board.close()
    # Wait for clean exit
    time.sleep(10)
    board = connect_board()
    rc, ps = run(board, "ps | grep sample_dtof | grep -v grep || echo CLEAN")
    print(f"After kill: {ps.strip()}")
    board.close()

    # 3. Upload binary to board
    print("\n=== Uploading new binary to board ===")
    board = connect_board()
    sftp_board = board.open_sftp()
    with sftp_board.file(BOARD_DEST, 'wb') as f:
        f.write(binary_data)
    sftp_board.close()
    run(board, f"chmod +x {BOARD_DEST}")
    rc, ls = run(board, f"ls -la {BOARD_DEST}")
    print(f"Deployed: {ls.strip()}")
    board.close()
    print(f"Binary size on board should be {len(binary_data)} bytes")

    # 4. Reboot for clean ISP state
    print("\n=== Rebooting board for clean state ===")
    board = connect_board()
    board.exec_command("reboot", timeout=5)
    board.close()
    print("Waiting for reboot...")
    time.sleep(25)
    if not wait_board(120):
        print("Board didn't come back!")
        return
    print("Board is back!")

    # 5. Kill S90autorun binary and start mode 3 manually with log
    time.sleep(5)
    print("\n=== Killing S90autorun binary (SIGTERM) ===")
    board = connect_board()
    run(board, "pkill -15 -f sample_dtof_os08a20 2>/dev/null")
    board.close()
    # Wait for clean exit
    deadline = time.time() + 25
    while time.time() < deadline:
        time.sleep(3)
        board = connect_board()
        rc, ps = run(board, "ps | grep sample_dtof | grep -v grep || echo CLEAN")
        board.close()
        if "CLEAN" in ps or "sample_dtof" not in ps:
            print(f"Binary gone: {ps.strip()}")
            break
    else:
        print("WARNING: binary still running, force kill")
        board = connect_board()
        run(board, "pkill -9 -f sample_dtof_os08a20 2>/dev/null; sleep 2")
        board.close()

    time.sleep(3)

    # 6. Start mode 3 with log
    print("\n=== Starting new binary in mode 3 ===")
    board = connect_board()
    rc, out = run(board,
        "cd /opt/sample/dtof && sh ./dtof_init.sh 2>/dev/null; "
        "(sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 2>&1) > /tmp/mode3_new.log 2>&1 & echo PID=$!")
    print(f"Start: {out.strip()}")
    board.close()

    # 7. Wait 30s and check
    print("Waiting 30s for init...")
    time.sleep(30)

    print("\n=== Status at t=30s ===")
    board = connect_board()
    rc, ps2 = run(board, "ps | grep sample_dtof | grep -v grep || echo GONE")
    print(f"Binary: {ps2.strip()}")

    rc, vi = run(board, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"\nVI status:\n{vi}")

    rc, mipi = run(board, "cat /proc/umap/mipi_rx | grep 'freq\\|phy_id' | head -6")
    print(f"\nMIPI freq:\n{mipi}")

    rc, reg = run(board, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null || echo 'I2C failed'")
    print(f"\nOS08A20 0x0100: {reg.strip()}")

    rc, log = run(board, "head -5 /tmp/mode3_new.log 2>/dev/null")
    print(f"\nLog head:\n{log}")
    board.close()

    # 8. Wait more and check VENC
    print("\nWaiting 30 more seconds...")
    time.sleep(30)

    print("\n=== Status at t=60s ===")
    board = connect_board()
    rc, vi2 = run(board, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"VI status:\n{vi2}")

    rc, venc = run(board, "cat /proc/umap/venc | grep 'sequence\\|started\\|width' | head -10 2>/dev/null")
    print(f"\nVENC:\n{venc}")

    rc, detect = run(board, "cat /proc/umap/mipi_rx | grep -A5 'detect info'")
    print(f"\nMIPI detect:\n{detect}")

    rc, log2 = run(board, "head -10 /tmp/mode3_new.log 2>/dev/null")
    print(f"\nFull log head:\n{log2}")
    board.close()

if __name__ == "__main__":
    main()
