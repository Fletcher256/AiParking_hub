"""Download binary from VM, patch GLIBC versions, deploy to board, test."""
import paramiko, stat, subprocess, sys, os

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
BINARY     = 'sample_os08a20_dtof'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
LOCAL_BIN  = rf'D:\parking_board_agent\board_files\{BINARY}'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

# ── 1. Download binary from VM ─────────────────────────────────────────────
print("=== 1. Downloading binary from VM ===")
vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)
sftp = vm.open_sftp()
sftp.get(f'{BUILD}/{BINARY}', LOCAL_BIN)
sftp.close()
vm.close()
size = os.path.getsize(LOCAL_BIN)
print(f"Downloaded: {LOCAL_BIN} ({size} bytes)")

# ── 2. Patch GLIBC versions ────────────────────────────────────────────────
print("\n=== 2. Patching GLIBC version requirements ===")
result = subprocess.run(
    [sys.executable, r'D:\parking_board_agent\board_files\patch_elf_glibc.py', LOCAL_BIN],
    capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
if result.returncode != 0:
    print("Patch FAILED — aborting")
    sys.exit(1)

# ── 3. Verify: check remaining GLIBC deps with strings ────────────────────
print("=== 3. Verifying patched binary ===")
with open(LOCAL_BIN, 'rb') as f:
    content = f.read()
# Quick check: GLIBC_2.33 and GLIBC_2.34 should no longer appear as null-terminated strings
glibc_33 = b'GLIBC_2.33\x00'
glibc_34 = b'GLIBC_2.34\x00'
if glibc_33 in content or glibc_34 in content:
    print(f"WARNING: GLIBC_2.33/2.34 still found as null-terminated strings in binary!")
else:
    print("OK: GLIBC_2.33 and GLIBC_2.34 not found in binary strings")

# ── 4. Deploy patched binary to board ─────────────────────────────────────
print("\n=== 4. Deploying to board ===")
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

sftp2 = b.open_sftp()
sftp2.put(LOCAL_BIN, f'{DEST_DIR}/{BINARY}')
sftp2.chmod(f'{DEST_DIR}/{BINARY}',
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
sftp2.close()

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

rc, o, _ = run_b(f'ls -lh {DEST_DIR}/{BINARY}')
print("Board:", o.strip())

# ── 5. Kill old processes and check ko modules ─────────────────────────────
print("\n=== 5. Environment check ===")
run_b("pkill -f sample_vio 2>/dev/null; pkill -f sample_dtof 2>/dev/null; pkill -f sample_os08a20 2>/dev/null; sleep 1")
rc, o, _ = run_b("lsmod | grep -E 'ot_isp|ot_vi|ot_mipi_rx'")
print("KO modules:\n", o.strip() or "(none)")
rc, o, _ = run_b("ps aux | grep -E 'sample_vio|sample_dtof|sample_os08a20' | grep -v grep")
print("Running:", o.strip() or "(none)")

b.close()
print("\nReady to run binary on board.")
