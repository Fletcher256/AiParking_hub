"""从 VM 直接 SCP 静态二进制到板子并运行，观察输出."""
import paramiko, time, sys

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
BINARY     = 'sample_os08a20_dtof'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

# ── 1. 从 VM SCP 到板子 ──────────────────────────────────────────────────
print("=== 1. SCP static binary VM -> board ===")
vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# 确认 VM 上是静态版本
rc, o, _ = run_vm(f"file {BUILD}/{BINARY} && ls -lh {BUILD}/{BINARY}")
print("VM binary:", o.strip())

# 如果不是 statically linked，停止
if 'statically linked' not in o:
    print("ERROR: VM binary is NOT static! Run build_static.py first.")
    vm.close(); sys.exit(1)

rc, o, e = run_vm(
    f'sshpass -p {PASS_B} scp {SSH_OPTS} {BUILD}/{BINARY} '
    f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/{BINARY}', timeout=30
)
print(f"SCP rc={rc}", e.strip() if e.strip() else "OK")

rc, o, _ = run_vm(
    f'sshpass -p {PASS_B} ssh {SSH_OPTS} {USER_B}@{HOST_BOARD} '
    f'"ls -lh {DEST_DIR}/{BINARY}"'
)
print("Board:", o.strip())
vm.close()

# ── 2. 连板子直接运行 ────────────────────────────────────────────────────
print("\n=== 2. Connecting to board ===")
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

run_b("pkill -f sample_vio 2>/dev/null; pkill -f sample_dtof 2>/dev/null; "
      "pkill -f sample_os08a20 2>/dev/null; sleep 1")
rc, o, _ = run_b("lsmod | grep -E 'ot_isp|ot_vi|ot_mipi_rx' | head -5")
print("KO:", o.strip() or "(none)")

# ── 3. 运行，观察 10 秒 ──────────────────────────────────────────────────
print(f"\nLaunching: cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")

start = time.time()
chan.settimeout(1.0)
while time.time() - start < 12:
    try:
        data = chan.recv(4096)
        if not data:
            print("\n[process exited]"); break
        sys.stdout.write(data.decode(errors='replace'))
        sys.stdout.flush()
    except Exception:
        pass

print("\n\n=== After 12s ===")
rc, o, _ = run_b("ps aux | grep sample_os08a20 | grep -v grep")
print("Process:", o.strip() or "(not running)")
b.close()
