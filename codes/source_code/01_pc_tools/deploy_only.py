#!/usr/bin/env python3
"""Deploy binary from VM to board and reboot."""
import paramiko, time

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
BUILD_DIR = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof"

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

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()

    # Find what binary was built
    print("=== Files in build dir ===")
    out = run(vm, f"ls -lh {BUILD_DIR}/ | grep -v '\\.c\|\\.[oh]\|Makefile\|ini\|bak'")
    print(out.strip())

    # Find the binary (no extension, executable)
    out = run(vm, f"find {BUILD_DIR} -maxdepth 1 -type f -executable ! -name '*.py' ! -name '*.sh' 2>/dev/null")
    print(f"Executables: {out.strip()}")

    # The binary on board
    print("\n=== Binary on board ===")
    board = connect_board()
    out = run(board, "ls -lh /opt/sample/dtof/ | grep sample_dtof")
    print(out.strip())

    # The binary name on board
    board_bin_path = None
    for line in out.strip().split('\n'):
        if 'sample_dtof' in line and not line.startswith('d'):
            parts = line.split()
            board_bin_path = f"/opt/sample/dtof/{parts[-1]}"
            break
    print(f"Board binary path: {board_bin_path}")
    board.close()

    # Find matching VM binary
    vm_bin = f"{BUILD_DIR}/sample_dtof"
    out = run(vm, f"ls -lh {vm_bin} 2>/dev/null || echo NOT_FOUND")
    print(f"VM binary {vm_bin}: {out.strip()}")

    if "NOT_FOUND" not in out and board_bin_path:
        # Deploy
        print(f"\n=== Deploying {vm_bin} to board:{board_bin_path} ===")
        out = run(vm,
            f"sshpass -p '{BOARD_PASS}' scp -o StrictHostKeyChecking=no "
            f"{vm_bin} {BOARD_USER}@{BOARD_HOST}:{board_bin_path} 2>&1",
            timeout=60)
        print(out.strip() or "OK (no output)")

        # Verify on board
        board = connect_board()
        out = run(board, f"ls -lh {board_bin_path}")
        print(f"Board binary after deploy: {out.strip()}")

        # Restore S90autorun (single dtof_init.sh, sleep 3)
        print("\n=== Restoring S90autorun ===")
        new_autorun = (
            "#!/bin/sh\n"
            "ip addr add 192.168.137.2/24 dev eth0 2>/dev/null\n"
            "cd /opt/ko\n"
            "./load_ss928v100 -i -sensor0 os08a20\n"
            "cd /opt/sample/dtof\n"
            "sh ./dtof_init.sh\n"
            "sleep 3\n"
            f"sleep 7200 | {board_bin_path} 3 192.168.137.100 > /tmp/dtof.log 2>&1 &\n"
        )
        write_cmd = f"python3 -c \"open('/etc/init.d/S90autorun','w').write({repr(new_autorun)})\""
        out = run(board, write_cmd)
        out = run(board, "chmod +x /etc/init.d/S90autorun && cat /etc/init.d/S90autorun")
        print(out.strip())

        # Reboot
        print("\n=== Rebooting board ===")
        try:
            board.exec_command("reboot", timeout=3)
        except:
            pass
        board.close()
        print("Board rebooting. Wait ~70s before checking.")
    else:
        print("Could not find binaries to deploy")
        board = connect_board()

    vm.close()

if __name__ == "__main__":
    main()
