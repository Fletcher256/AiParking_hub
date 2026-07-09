#!/usr/bin/env python3
"""Rebuild sample_dtof binary on VM and deploy to board."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
BUILD_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"
BIN_NAME = "sample_dtof_os08a20"
BOARD_BIN = f"/opt/sample/dtof/{BIN_NAME}"

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

def run(c, cmd, timeout=120):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()

    # 1. Build
    print("=== Building on VM ===")
    out = run(vm, f"bash -l -c 'cd {BUILD_DIR} && make -j4 2>&1'", timeout=120)
    print(out[-4000:])

    # 2. Check binary exists
    print("\n=== Check binary ===")
    out = run(vm, f"ls -lh {BUILD_DIR}/{BIN_NAME} 2>/dev/null || echo NOT_FOUND")
    print(out.strip())
    if "NOT_FOUND" in out or "sample_dtof" not in out:
        print("ERROR: Binary not built!")
        vm.close()
        return

    # 3. Copy binary from VM to board via sshpass scp
    print("\n=== Deploying binary to board ===")
    out = run(vm,
        f"sshpass -p '{BOARD_PASS}' scp -o StrictHostKeyChecking=no "
        f"{BUILD_DIR}/{BIN_NAME} {BOARD_USER}@{BOARD_HOST}:{BOARD_BIN} 2>&1",
        timeout=60)
    print(out.strip())

    # 4. Verify on board
    print("\n=== Verify on board ===")
    board = connect_board()
    out = run(board, f"ls -lh {BOARD_BIN} 2>/dev/null || echo NOT_FOUND")
    print(out.strip())

    # 5. Restore S90autorun to single dtof_init.sh (no need for double)
    print("\n=== Restoring S90autorun (single dtof_init.sh) ===")
    new_autorun = """#!/bin/sh
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20
cd /opt/sample/dtof
sh ./dtof_init.sh
sleep 3
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 > /tmp/dtof.log 2>&1 &
"""
    # Write via python on board
    write_cmd = f"python3 -c \"open('/etc/init.d/S90autorun','w').write({repr(new_autorun)})\""
    out = run(board, write_cmd)
    print(f"Write result: {repr(out)}")

    out = run(board, "chmod +x /etc/init.d/S90autorun && cat /etc/init.d/S90autorun")
    print(out.strip())

    # 6. Reboot board
    print("\n=== Rebooting board ===")
    try:
        board.exec_command("reboot", timeout=3)
    except:
        pass
    board.close()
    vm.close()
    print("Board rebooting... wait ~70 seconds for it to come back and binary to start")

if __name__ == "__main__":
    main()
