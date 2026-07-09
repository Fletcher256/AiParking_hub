#!/usr/bin/env python3
"""Reboot board and deploy new binary after reboot."""
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

def connect_board():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    # First reboot board to clear corrupted VB/ISP state
    print("=== Rebooting board to clear ISP/VB state ===")
    try:
        board = connect_board()
        board.exec_command("reboot", timeout=3)
        board.close()
        print("Reboot command sent")
    except Exception as e:
        print(f"Reboot: {e}")

    print("Waiting 60 seconds for board to come back...")
    time.sleep(60)

    # Connect to board
    for i in range(10):
        try:
            board = connect_board()
            print(f"Board connected (attempt {i+1})")
            break
        except Exception as e:
            print(f"Attempt {i+1}: {e}")
            time.sleep(8)
    else:
        print("FAILED to connect to board")
        return

    print("\n=== Board uptime ===")
    print(run(board, "uptime").strip())

    # Deploy new binary from VM
    print("\n=== Deploying new binary ===")
    vm = connect_vm()
    out = run(vm,
        f"sshpass -p '{BOARD_PASS}' scp -o StrictHostKeyChecking=no "
        f"{VM_BIN} {BOARD_USER}@{BOARD_HOST}:{BOARD_BIN} 2>&1",
        timeout=60)
    print(out.strip() or "OK")
    vm.close()

    # Verify binary on board
    out = run(board, f"ls -lh {BOARD_BIN}")
    print(f"Board binary: {out.strip()}")

    # Update S90autorun with single dtof_init.sh, sleep 3
    print("\n=== Updating S90autorun ===")
    new_autorun = (
        "#!/bin/sh\n"
        "ip addr add 192.168.137.2/24 dev eth0 2>/dev/null\n"
        "cd /opt/ko\n"
        "./load_ss928v100 -i -sensor0 os08a20\n"
        "cd /opt/sample/dtof\n"
        "sh ./dtof_init.sh\n"
        "sleep 3\n"
        f"sleep 7200 | {BOARD_BIN} 3 192.168.137.100 > /tmp/dtof.log 2>&1 &\n"
    )
    run(board, f"python3 -c \"open('/etc/init.d/S90autorun','w').write({repr(new_autorun)})\"")
    run(board, "chmod +x /etc/init.d/S90autorun")
    print(run(board, "cat /etc/init.d/S90autorun").strip())

    # Reboot again with new binary
    print("\n=== Final reboot to start with new binary ===")
    try:
        board.exec_command("reboot", timeout=3)
    except:
        pass
    board.close()
    print("Board rebooting with new binary. Wait ~90 seconds...")

if __name__ == "__main__":
    main()
