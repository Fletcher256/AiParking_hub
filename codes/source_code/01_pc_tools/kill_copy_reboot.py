#!/usr/bin/env python3
"""Kill binary, copy new one, reboot."""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_BIN = "/opt/sample/dtof/sample_dtof"
VM_BIN = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"

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

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    # Wait for board to come back from reboot
    print("Waiting for board to come up...")
    board = None
    for i in range(15):
        try:
            board = connect_board()
            print(f"Connected (attempt {i+1})")
            break
        except Exception as e:
            print(f"  {i+1}: {e}")
            time.sleep(8)
    if not board:
        print("FAILED to connect")
        return

    print("\n=== Current binary ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo NONE").strip())

    # Kill binary with SIGTERM
    print("\n=== Kill binary (SIGTERM) ===")
    run(board, "pkill -TERM sample_dtof")
    print("SIGTERM sent, waiting 8s...")
    time.sleep(8)

    out = run(board, "ps | grep sample_dtof | grep -v grep || echo 'gone'")
    print(f"After SIGTERM: {out.strip()}")

    # If still running, SIGTERM + more wait
    if 'sample_dtof' in out:
        run(board, "pkill -TERM sample_dtof")
        time.sleep(5)

    # Copy to /tmp first, then move (to avoid "text file busy")
    print("\n=== Deploying binary via /tmp ===")
    vm = connect_vm()
    out = run(vm,
        f"sshpass -p '{BOARD_PASS}' scp -o StrictHostKeyChecking=no "
        f"{VM_BIN} {BOARD_USER}@{BOARD_HOST}:/tmp/sample_dtof_new 2>&1",
        timeout=60)
    print(f"scp to /tmp: {out.strip() or 'OK'}")
    vm.close()

    # Move to final location
    out = run(board, f"mv /tmp/sample_dtof_new {BOARD_BIN} && chmod +x {BOARD_BIN} && echo 'moved OK'")
    print(f"move: {out.strip()}")

    out = run(board, f"ls -lh {BOARD_BIN}")
    print(f"Board binary: {out.strip()}")

    # Reboot to test
    print("\n=== Rebooting for final test ===")
    try:
        board.exec_command("reboot", timeout=3)
    except:
        pass
    board.close()
    print("Board rebooting. Wait ~90s then check log.")
    print("Expected: pre-warm takes ~13s, then DtofInit success, no frame errors")

if __name__ == "__main__":
    main()
