"""Upload modified C file, rebuild static binary, deploy to board, run."""
import paramiko, stat, time, sys, io

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
BINARY     = 'sample_os08a20_dtof'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)
sftp = vm.open_sftp()

def run_vm(cmd, timeout=180):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# 1. 上传修改后的 C 源文件
print("=== 1. Upload os08a20_dtof.c ===")
sftp.put(r'D:\parking_board_agent\board_files\os08a20_dtof\os08a20_dtof.c',
         f'{BUILD}/os08a20_dtof.c')
print("OK")

# 2. 只重新编译修改的文件（增量 make）
print("\n=== 2. Incremental make (static) ===")
rc, o, e = run_vm(f"cd {BUILD} && make 2>&1")
lines = (o + e).splitlines()
errors = [l for l in lines if 'error:' in l.lower()]
if errors:
    print("ERRORS:")
    for l in errors[:20]: print(" ", l)
    print("Last 10 lines:")
    for l in lines[-10:]: print(" ", l)
    sftp.close(); vm.close(); sys.exit(1)
# 只打最后几行
for l in lines[-5:]: print(" ", l)
print(f"rc={rc}")

# 3. 确认是静态二进制
rc, o, _ = run_vm(f"file {BUILD}/{BINARY} && ls -lh {BUILD}/{BINARY}")
print("\nBinary:", o.strip())
if 'statically linked' not in o:
    print("ERROR: not static!")
    sftp.close(); vm.close(); sys.exit(1)

# 4. SCP 到板子
print("\n=== 3. Deploy to board ===")
rc, o, e = run_vm(
    f'sshpass -p {PASS_B} scp {SSH_OPTS} {BUILD}/{BINARY} '
    f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/{BINARY}', timeout=30)
print(f"SCP rc={rc}", e.strip() if e.strip() else "OK")
sftp.close(); vm.close()

# 5. 在板子上运行
print("\n=== 4. Run on board ===")
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode()

run_b(f"pkill -f {BINARY} 2>/dev/null; sleep 1")

print(f"Launching ./{BINARY} 1 192.168.137.1 ...\n")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")

start = time.time()
chan.settimeout(1.0)
while time.time() - start < 15:
    try:
        data = chan.recv(4096)
        if not data:
            print("\n[process exited early]"); break
        sys.stdout.write(data.decode(errors='replace'))
        sys.stdout.flush()
    except Exception:
        pass

print("\n\n=== After 15s ===")
o = run_b(f"ps aux | grep {BINARY} | grep -v grep")
print("Process:", o.strip() or "(not running)")
b.close()
