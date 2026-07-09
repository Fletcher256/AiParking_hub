#!/usr/bin/env python3
"""
Restore original source files and rebuild with no pre-warm patches.
Fix: S90autorun sleep will be changed to 15s instead of 3s.
"""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"
VI_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"

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

    # === Step 1: Restore original source files ===
    print("=== Restoring sample_dtof.c from backup ===")
    out = run(vm, f"cp {SRC}.bak_prewarm {SRC} && echo restored")
    print(out.strip())

    print("\n=== Restoring sample_comm_vi.c from backup ===")
    out = run(vm, f"cp {VI_COMMON}.bak_prewarm {VI_COMMON} && echo restored")
    print(out.strip())

    # Verify clean state
    print("\n=== Verify sample_dtof.c is clean ===")
    out = run(vm, f"grep -n 'pre-warm' {SRC} | head -5")
    print(out.strip() or "(clean - no pre-warm patches)")

    print("\n=== Verify sample_comm_vi.c is clean ===")
    out = run(vm, f"grep -n 'restart_sensor_isp' {VI_COMMON} | head -5")
    print(out.strip() or "(clean - no restart_sensor_isp)")

    # === Step 2: Rebuild binary ===
    print("\n=== Rebuilding binary ===")
    out = run(vm,
        "bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -10'",
        timeout=180)
    print(out.strip())

    out = run(vm, "ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof")
    print(f"Binary: {out.strip()}")

    vm.close()

    # === Step 3: Deploy binary to board ===
    print("\n=== Deploying to board via SCP ===")
    board = connect_board()

    # Kill existing binary first
    print("Killing existing binary...")
    run(board, "pkill -TERM sample_dtof 2>/dev/null; sleep 3")
    out = run(board, "ps | grep sample_dtof | grep -v grep || echo gone")
    print(f"Process check: {out.strip()}")

    # SCP via VM (board connects via VM's SSH)
    vm2 = connect_vm()
    binary_path = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
    print("Copying binary to board /tmp/ ...")
    out = run(vm2,
        f"sshpass -p ebaina scp -o StrictHostKeyChecking=no {binary_path} root@192.168.137.2:/tmp/sample_dtof_new && echo scp_ok",
        timeout=60)
    print(out.strip())

    # Move on board
    out = run(board, "mv /tmp/sample_dtof_new /opt/sample/dtof/sample_dtof && chmod +x /opt/sample/dtof/sample_dtof && echo moved")
    print(out.strip())

    vm2.close()

    # === Step 4: Update S90autorun to sleep 15 instead of 3 ===
    print("\n=== Updating S90autorun (sleep 3 -> sleep 15) ===")
    out = run(board, "cat /etc/init.d/S90autorun")
    print("Current S90autorun:")
    print(out)

    # Read and patch
    current = out
    if "sleep 3" in current and "sleep 7200" in current:
        new_content = current.replace(
            "sleep 3\nsleep 7200 | /opt/sample/dtof/sample_dtof",
            "sleep 15\nsleep 7200 | /opt/sample/dtof/sample_dtof"
        )
        # Write via heredoc
        import base64
        encoded = base64.b64encode(new_content.encode()).decode()
        out2 = run(board, f"echo '{encoded}' | base64 -d > /etc/init.d/S90autorun && chmod +x /etc/init.d/S90autorun && echo updated")
        print(out2.strip())
    else:
        print("WARNING: Could not find expected pattern in S90autorun!")
        print("Manual check needed.")

    # Verify
    out = run(board, "cat /etc/init.d/S90autorun")
    print("\nUpdated S90autorun:")
    print(out)

    board.close()

    print("\n=== Done! Reboot board to test. ===")
    print("After reboot, check: tail -f /tmp/dtof.log")
    print("Expected: no 92 I2C errors (or much fewer) on startup")

if __name__ == "__main__":
    main()
