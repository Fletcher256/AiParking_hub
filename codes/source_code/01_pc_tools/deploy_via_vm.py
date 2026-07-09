#!/usr/bin/env python3
"""Deploy binary via VM: VM scp directly to board."""
import paramiko, time

VM_HOST    = "192.168.137.100"
VM_USER    = "ebaina"
VM_PASS    = "ebaina"
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

def run_vm(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def run_board(c, cmd, timeout=60):
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
    # 1. Check VM can reach board and binary is ready
    print("=== Check VM binary ===")
    vm = connect_vm()
    rc, ls = run_vm(vm, f"ls -la {VM_BINARY}")
    print(ls.strip())

    # 2. SCP from VM to board (using sshpass or expect)
    print("\n=== SCP binary from VM to board ===")
    # First check if sshpass is available
    rc, sshpass = run_vm(vm, "which sshpass 2>/dev/null || echo 'NO_SSHPASS'")
    print(f"sshpass: {sshpass.strip()}")

    if "NO_SSHPASS" not in sshpass:
        # Use sshpass for non-interactive scp
        scp_cmd = (f"sshpass -p '{BOARD_PASS}' scp -o StrictHostKeyChecking=no "
                   f"{VM_BINARY} {BOARD_USER}@{BOARD_HOST}:{BOARD_DEST}")
        rc, out = run_vm(vm, scp_cmd, timeout=120)
        print(f"SCP rc={rc}: {out.strip()}")
    else:
        # Alternative: use expect
        rc, exp = run_vm(vm, "which expect 2>/dev/null || echo 'NO_EXPECT'")
        print(f"expect: {exp.strip()}")

        if "NO_EXPECT" not in exp:
            expect_cmd = f"""expect -c "
spawn scp -o StrictHostKeyChecking=no {VM_BINARY} {BOARD_USER}@{BOARD_HOST}:{BOARD_DEST}
expect 'password:'
send '{BOARD_PASS}\\n'
expect eof
" """
            rc, out = run_vm(vm, expect_cmd, timeout=120)
            print(f"expect scp rc={rc}: {out.strip()}")
        else:
            # Last resort: use python on VM to do the transfer
            upload_script = f'''
import paramiko
BOARD_HOST="{BOARD_HOST}"
BOARD_USER="{BOARD_USER}"
BOARD_PASS="{BOARD_PASS}"
VM_BINARY="{VM_BINARY}"
BOARD_DEST="{BOARD_DEST}"

# Read local binary
with open(VM_BINARY, "rb") as f:
    data = f.read()
print(f"Read {{len(data)}} bytes")

# Connect to board
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)

# Try exec cat approach
import base64, hashlib

# Split into chunks and transfer via echo/base64
chunk_size = 32768  # 32KB chunks
chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
print(f"Uploading in {{len(chunks)}} chunks...")

# Start fresh file
_, stdout, stderr = c.exec_command(f"> {{BOARD_DEST}}")
stdout.channel.recv_exit_status()

for i, chunk in enumerate(chunks):
    b64 = base64.b64encode(chunk).decode()
    cmd = f"echo {{b64}} | base64 -d >> {{BOARD_DEST}}"
    _, stdout, stderr = c.exec_command(cmd, timeout=30)
    stdout.channel.recv_exit_status()
    if (i+1) % 10 == 0:
        print(f"  chunk {{i+1}}/{{len(chunks)}}...")

# Verify size
_, stdout, stderr = c.exec_command(f"wc -c {{BOARD_DEST}}")
size = stdout.read().decode().strip()
print(f"Board file size: {{size}} (expected {{len(data)}})")

_, stdout, stderr = c.exec_command(f"chmod +x {{BOARD_DEST}}")
stdout.channel.recv_exit_status()
c.close()
print("Transfer complete!")
'''
            sftp_vm = vm.open_sftp()
            with sftp_vm.file("/tmp/transfer.py", 'w') as f:
                f.write(upload_script)
            sftp_vm.close()
            rc, out = run_vm(vm, "pip install paramiko -q 2>/dev/null; python3 /tmp/transfer.py", timeout=600)
            print(f"Transfer result (rc={rc}):\n{out.strip()}")

    vm.close()

    # 3. Verify on board
    print("\n=== Verify binary on board ===")
    board = connect_board()
    rc, ls2 = run_board(board, f"ls -la {BOARD_DEST}; md5sum {BOARD_DEST}")
    print(ls2.strip())
    board.close()

if __name__ == "__main__":
    main()
