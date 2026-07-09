"""Rebuild with -static on VM, check result, deploy to board."""
import paramiko, stat, sys

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
BINARY     = 'sample_os08a20_dtof'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run(cmd, timeout=120):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# ── 1. 检查静态库是否是真实实现 ──────────────────────────────────────────
print("=== 1. Checking static libs ===")
rc, o, _ = run("file /usr/aarch64-linux-gnu/lib/libc.a "
               "/usr/aarch64-linux-gnu/lib/libpthread.a "
               "/usr/aarch64-linux-gnu/lib/libdl.a "
               "/usr/aarch64-linux-gnu/lib/libstdc++.a 2>&1")
print(o.strip())
rc, o, _ = run("ls -lh /usr/aarch64-linux-gnu/lib/libc.a "
               "/usr/aarch64-linux-gnu/lib/libpthread.a")
print(o.strip())

# ── 2. 上传带 -static 的 Makefile ─────────────────────────────────────────
print("\n=== 2. Writing static Makefile ===")
sftp = vm.open_sftp()

# 读本地 Makefile.cross，修改 link 行加 -static
with open(r'D:\parking_board_agent\board_files\os08a20_dtof\Makefile.cross', 'r') as f:
    mk = f.read()

# 把 link 行的 -lpthread -lm -ldl -lstdc++ 改为 -static 版本
mk = mk.replace(
    '-lpthread -lm -ldl -lstdc++',
    '-static -lpthread -lm -ldl -lstdc++ -lgcc_eh -lgcc'
)

import io
sftp.putfo(io.BytesIO(mk.encode()), f'{BUILD}/Makefile')
sftp.close()
print("Makefile uploaded (link step has -static)")
print("Link line:", [l.strip() for l in mk.splitlines() if '-static' in l])

# ── 3. Clean + build ──────────────────────────────────────────────────────
print("\n=== 3. Building (static) ===")
rc, o, e = run(f"cd {BUILD} && make clean && make 2>&1", timeout=180)
# 只显示最后部分（含错误）
lines = (o + e).splitlines()
# 显示所有 error 行 + 最后 30 行
errors = [l for l in lines if 'error:' in l.lower() or 'undefined ref' in l.lower()]
if errors:
    print("ERRORS:")
    for l in errors[:40]:
        print(" ", l)
print("\nLast 20 lines:")
for l in lines[-20:]:
    print(" ", l)
print(f"\nrc={rc}")

if rc != 0:
    print("Build FAILED")
    vm.close(); sys.exit(1)

# ── 4. 检查生成的二进制 ───────────────────────────────────────────────────
print("\n=== 4. Check binary ===")
rc, o, _ = run(f"ls -lh {BUILD}/{BINARY} && "
               f"file {BUILD}/{BINARY} && "
               f"strings {BUILD}/{BINARY} | grep 'GLIBC_2\\.' | sort -u")
print(o.strip())

# ── 5. 部署到板子（通过 VM SCP）────────────────────────────────────────────
print("\n=== 5. Deploying ===")
rc, o, e = run(
    f'sshpass -p {PASS_B} scp {SSH_OPTS} {BUILD}/{BINARY} '
    f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/{BINARY}',
    timeout=30
)
print(f"SCP rc={rc}", e.strip() if e.strip() else "OK")

rc, o, _ = run(
    f'sshpass -p {PASS_B} ssh {SSH_OPTS} {USER_B}@{HOST_BOARD} '
    f'"ls -lh {DEST_DIR}/{BINARY}"'
)
print("Board:", o.strip())
vm.close()
