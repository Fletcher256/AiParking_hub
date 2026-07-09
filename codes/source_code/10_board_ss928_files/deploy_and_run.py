"""Deploy patched binary to board via VM scp, then run it and watch output."""
import paramiko, time, sys, stat

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
BINARY     = 'sample_os08a20_dtof'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
LOCAL_BIN  = rf'D:\parking_board_agent\board_files\{BINARY}'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

# ── 1. Upload patched binary to VM ────────────────────────────────────────
print("=== 1. Uploading patched binary to VM ===")
vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)
sftp = vm.open_sftp()
sftp.put(LOCAL_BIN, f'{BUILD}/{BINARY}')
sftp.close()
print("Upload OK")

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# ── 2. SCP from VM to board ───────────────────────────────────────────────
print("\n=== 2. SCP to board ===")
rc, o, e = run_vm(
    f'sshpass -p {PASS_B} scp {SSH_OPTS} {BUILD}/{BINARY} '
    f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/{BINARY}',
    timeout=30
)
print(f"SCP rc={rc}", e.strip() if e.strip() else "OK")

# Verify
rc, o, _ = run_vm(
    f'sshpass -p {PASS_B} ssh {SSH_OPTS} {USER_B}@{HOST_BOARD} '
    f'"ls -lh {DEST_DIR}/{BINARY} && strings {DEST_DIR}/{BINARY} | grep GLIBC_2\\.3"'
)
print("Board verify:\n", o.strip())
vm.close()

# ── 3. Connect to board directly and run binary ───────────────────────────
print("\n=== 3. Running binary on board ===")
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Kill old processes
run_b("pkill -f sample_vio 2>/dev/null; pkill -f sample_dtof 2>/dev/null; "
      "pkill -f sample_os08a20 2>/dev/null; sleep 1")
rc, o, _ = run_b("ps aux | grep -E 'sample_vio|sample_dtof|sample_os08a20' | grep -v grep")
print("Running before launch:", o.strip() or "(none)")

# Check ko modules
rc, o, _ = run_b("lsmod | grep -E 'ot_isp|ot_vi|ot_mipi_rx'")
print("KO loaded:", o.strip() or "(none)")

# ── 4. Launch binary, capture first 10 seconds ───────────────────────────
print("\nLaunching ./sample_os08a20_dtof 1 192.168.137.1 ...")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./sample_os08a20_dtof 1 192.168.137.1")

start = time.time()
output_lines = []
chan.settimeout(1.0)
while time.time() - start < 10:
    try:
        data = chan.recv(4096)
        if not data:
            print("[process exited]")
            break
        text = data.decode(errors='replace')
        print(text, end='', flush=True)
        output_lines.append(text)
    except Exception:
        pass

print("\n\n=== After 10s ===")
rc, o, _ = run_b("ps aux | grep sample_os08a20 | grep -v grep")
print("Process:", o.strip() or "(not running)")

b.close()
