#!/usr/bin/env python3
"""Download new sample_dtof binary from VM and deploy to board."""
import paramiko, sys, os

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
VM_BINARY = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
LOCAL_TMP = "C:/Windows/Temp/sample_dtof_new"

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
BOARD_DEST = "/opt/sample/dtof/sample_dtof_os08a20"

def main():
    # Step 1: Download from VM
    print(f"[1] Downloading from VM {VM_HOST}...")
    vm = paramiko.SSHClient()
    vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    vm.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    sftp = vm.open_sftp()
    sftp.get(VM_BINARY, LOCAL_TMP)
    sftp.close()
    vm.close()
    sz = os.path.getsize(LOCAL_TMP)
    print(f"    Downloaded {sz} bytes -> {LOCAL_TMP}")

    # Step 2: Upload to board via stdin pipe
    print(f"[2] Uploading to board {BOARD_HOST}:{BOARD_DEST}...")
    board = paramiko.SSHClient()
    board.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    board.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                  timeout=30, banner_timeout=30, auth_timeout=30)
    chan = board.get_transport().open_session()
    chan.exec_command(f"cat > {BOARD_DEST}")
    with open(LOCAL_TMP, "rb") as f:
        data = f.read()
    for i in range(0, len(data), 32768):
        chan.sendall(data[i:i+32768])
    chan.shutdown_write()
    rc = chan.recv_exit_status()
    board.close()
    print(f"    Upload rc={rc}")

    # Step 3: chmod +x
    print(f"[3] Setting executable bit...")
    board2 = paramiko.SSHClient()
    board2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    board2.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    _, stdout, stderr = board2.exec_command(f"chmod +x {BOARD_DEST} && ls -la {BOARD_DEST}", timeout=15)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    board2.close()
    if out: print(out, end="")
    if err: print(err, end="", file=sys.stderr)
    print("Done!")

if __name__ == "__main__":
    main()
