"""Reset KO module state then run the binary."""
import paramiko, time, sys

HOST_BOARD = '192.168.137.2'; USER_B = 'root'; PASS_B = 'ebaina'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
BINARY     = 'sample_os08a20_dtof'

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=15):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode() + err.read().decode()

# 1. 杀掉所有 sample 进程
print("=== 1. Kill all sample processes ===")
rc, o = run("pkill -9 -f sample 2>/dev/null; sleep 2; "
            "ps aux | grep sample | grep -v grep")
print("Remaining:", o.strip() or "(none)")

# 2. 卸载 KO 模块（反向依赖顺序）
print("\n=== 2. Unload KO modules ===")
for mod in ['ot_vi', 'ot_isp', 'ot_mipi_rx']:
    rc, o = run(f"rmmod {mod} 2>&1")
    print(f"  rmmod {mod}: {'OK' if rc==0 else o.strip()}")

rc, o = run("lsmod | grep -E 'ot_isp|ot_vi|ot_mipi'")
print("After unload:", o.strip() or "(none loaded)")

# 3. 重新加载 KO 模块（正向顺序）
print("\n=== 3. Reload KO modules from /opt/ko/ ===")
# 先确认 ko 文件在哪里
rc, o = run("ls /opt/ko/ot_mipi_rx.ko /opt/ko/ot_isp.ko /opt/ko/ot_vi.ko 2>&1")
print("KO files:", o.strip())

for ko in ['ot_mipi_rx.ko', 'ot_isp.ko', 'ot_vi.ko']:
    rc, o = run(f"insmod /opt/ko/{ko} 2>&1")
    print(f"  insmod {ko}: {'OK' if rc==0 else o.strip()}")

rc, o = run("lsmod | grep -E 'ot_isp|ot_vi|ot_mipi_rx'")
print("After reload:", o.strip() or "(none loaded)")

# 3.5 运行 dtof_init.sh 复位 GS1860 (GPIO 96 reset)
print("\n=== 3.5. Run dtof_init.sh to reset GS1860 ===")
rc, o = run("sh /opt/sample/dtof/dtof_init.sh 2>&1; echo 'dtof_init.sh done'", timeout=10)
print(o.strip())
import time as _time; _time.sleep(1)  # wait 1s for GS1860 to exit reset

# 4. 运行二进制，观察 15 秒
print(f"\n=== 4. Run ./{BINARY} 1 192.168.137.1 ===\n")
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
rc, o = run(f"ps aux | grep {BINARY} | grep -v grep")
print("Process:", o.strip() or "(not running)")
b.close()
