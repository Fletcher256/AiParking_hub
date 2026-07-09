"""把配置文件复制到 demo 目录，然后运行二进制."""
import paramiko, time, sys

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
BUILD      = '/home/ebaina/os08a20_dtof_build'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
BINARY     = 'sample_os08a20_dtof'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

# ── 1. 检查 VM build 目录里有哪些配置文件 ────────────────────────────────
print("=== 1. Config files in VM build dir ===")
vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

rc, o, _ = run_vm(f"find {BUILD} -name '*.ini' -o -name '*.cfg' 2>/dev/null | head -40")
print(o.strip())

rc, o, _ = run_vm(f"ls {BUILD}/param/ 2>/dev/null || echo 'no param dir'")
print("param/:", o.strip())

rc, o, _ = run_vm(f"ls {BUILD}/scene_auto/param/ 2>/dev/null || echo 'no scene_auto/param'")
print("scene_auto/param/:", o.strip())

# ── 2. 板子上 dtof 目录里有什么 ──────────────────────────────────────────
print("\n=== 2. Files in /opt/sample/dtof on board ===")
rc, o, e = run_vm(
    f'sshpass -p {PASS_B} ssh {SSH_OPTS} {USER_B}@{HOST_BOARD} '
    f'"ls -la /opt/sample/dtof/ && ls -la /opt/sample/mipi_imx347_dtof_only/"'
)
print(o.strip())

# ── 3. 把板子上已有的 ini 文件链接/复制到 demo 目录 ──────────────────────
print("\n=== 3. Copying ini files to demo dir ===")
cmds = [
    # gs1860_register.ini 从 dtof 目录复制
    f'cp /opt/sample/dtof/gs1860_register.ini {DEST_DIR}/gs1860_register.ini',
    # dtof.ini 也复制过去
    f'cp /opt/sample/dtof/dtof.ini {DEST_DIR}/dtof.ini 2>/dev/null || true',
    # 创建 param 目录（scene auto 配置）
    f'mkdir -p {DEST_DIR}/param',
]
for cmd in cmds:
    rc, o, e = run_vm(
        f'sshpass -p {PASS_B} ssh {SSH_OPTS} {USER_B}@{HOST_BOARD} "{cmd}"'
    )
    print(f"  [{rc}] {cmd.split('/')[-1]}", e.strip() if e.strip() else "OK")

# ── 4. 从 VM 复制 param/config_cfgaccess*.ini 到板子（如果存在）────────────
rc, o, _ = run_vm(f"find {BUILD} -path '*/param/*.ini' 2>/dev/null")
param_inis = [l.strip() for l in o.strip().splitlines() if l.strip()]
if param_inis:
    print(f"\nFound {len(param_inis)} param ini files in VM, copying...")
    for ini in param_inis:
        basename = ini.split('/')[-1]
        dst = f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/param/{basename}'
        rc, o, e = run_vm(
            f'sshpass -p {PASS_B} scp {SSH_OPTS} {ini} {dst}', timeout=15
        )
        print(f"  [{rc}] {basename}", e.strip() if e.strip() else "OK")
else:
    print("\nNo param ini files in VM build dir")
    # scene auto 可能在 open_camera 源码的 scene_auto/param 里
    rc, o, _ = run_vm(
        f"find /home/ebaina -path '*/scene_auto/param/*.ini' 2>/dev/null | head -5"
    )
    if o.strip():
        print("Found in scene_auto:", o.strip())
        for ini in o.strip().splitlines():
            basename = ini.split('/')[-1]
            dst = f'{USER_B}@{HOST_BOARD}:{DEST_DIR}/param/{basename}'
            rc2, o2, e2 = run_vm(
                f'sshpass -p {PASS_B} scp {SSH_OPTS} {ini} {dst}', timeout=15
            )
            print(f"  [{rc2}] {basename}", e2.strip() if e2.strip() else "OK")

vm.close()

# ── 5. 运行 ──────────────────────────────────────────────────────────────
print(f"\n=== 5. Running {BINARY} ===")
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

run_b(f"pkill -f {BINARY} 2>/dev/null; sleep 1")
rc, o, _ = run_b(f"ls -la {DEST_DIR}/")
print("Demo dir:\n", o.strip())

print(f"\nLaunching ./{BINARY} 1 192.168.137.1 ...")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")

start = time.time()
chan.settimeout(1.0)
while time.time() - start < 15:
    try:
        data = chan.recv(4096)
        if not data:
            print("\n[process exited]"); break
        sys.stdout.write(data.decode(errors='replace'))
        sys.stdout.flush()
    except Exception:
        pass

print("\n\n=== After 15s ===")
rc, o, _ = run_b(f"ps aux | grep {BINARY} | grep -v grep")
print("Process:", o.strip() or "(not running)")
b.close()
