#!/usr/bin/env python3
"""Restore everything to clean original state."""
import paramiko, base64

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
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    vm = connect_vm()

    # Restore both source files
    print("=== Restore sample_dtof.c ===")
    print(run(vm, f"cp {SRC}.bak_prewarm {SRC} && echo OK"))

    print("=== Restore sample_comm_vi.c ===")
    print(run(vm, f"cp {VI_COMMON}.bak_prewarm {VI_COMMON} && echo OK"))

    # Verify clean
    print("=== Verify no patches ===")
    print(run(vm, f"grep -c 'pre-warm\\|restart_sensor_isp\\|waiting 10s\\|vi_dev.*==.*2' {SRC} {VI_COMMON} 2>/dev/null || echo clean"))

    # Rebuild
    print("=== Rebuild ===")
    out = run(vm,
        "bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -3'",
        timeout=180)
    print(out.strip())
    print(run(vm, "ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"))

    vm.close()

    # Deploy to board
    board = connect_board()
    print("=== Kill binary ===")
    run(board, "pkill -TERM sample_dtof 2>/dev/null; sleep 3")
    print(run(board, "ps | grep sample_dtof | grep -v grep || echo gone"))

    vm2 = connect_vm()
    binary = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
    print("=== SCP to board ===")
    print(run(vm2, f"sshpass -p ebaina scp -o StrictHostKeyChecking=no {binary} root@192.168.137.2:/tmp/sample_dtof_new && echo OK", timeout=60))
    vm2.close()

    print(run(board, "mv /tmp/sample_dtof_new /opt/sample/dtof/sample_dtof && chmod +x /opt/sample/dtof/sample_dtof && echo OK"))

    # Restore S90autorun to sleep 3
    print("=== Restore S90autorun (sleep 15 -> sleep 3) ===")
    current = run(board, "cat /etc/init.d/S90autorun")
    if "sleep 15" in current:
        new_content = current.replace(
            "sleep 15\nsleep 7200 | /opt/sample/dtof/sample_dtof",
            "sleep 3\nsleep 7200 | /opt/sample/dtof/sample_dtof"
        )
        encoded = base64.b64encode(new_content.encode()).decode()
        print(run(board, f"echo '{encoded}' | base64 -d > /etc/init.d/S90autorun && chmod +x /etc/init.d/S90autorun && echo OK"))
    else:
        print("Already sleep 3 or different format")

    print("=== Final S90autorun ===")
    print(run(board, "cat /etc/init.d/S90autorun"))

    board.close()
    print("\n=== Done. All restored to original state. Waiting for your instruction. ===")

if __name__ == "__main__":
    main()
