"""Reset modules, run dtof_init.sh, start binary, check MIPI proc at 6s (during vi_bayerdump)."""
import paramiko, time, sys, threading

HOST_BOARD = '192.168.137.2'; USER_B = 'root'; PASS_B = 'ebaina'
DEST_DIR   = '/opt/sample/mipi_rgb_dtof_demo'
BINARY     = 'sample_os08a20_dtof'

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=30):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode() + err.read().decode()

# Setup: kill + reload + dtof_init
run("pkill -9 -f sample 2>/dev/null; sleep 2")
for mod in ['ot_vi', 'ot_isp', 'ot_mipi_rx']:
    run(f"rmmod {mod} 2>&1")
for ko in ['ot_mipi_rx.ko', 'ot_isp.ko', 'ot_vi.ko']:
    run(f"insmod /opt/ko/{ko} 2>&1")
run("sh /opt/sample/dtof/dtof_init.sh 2>&1; sleep 1")
print("Setup done, starting binary...")

chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")

output_lines = []
def collect_output():
    chan.settimeout(1.0)
    while True:
        try:
            data = chan.recv(4096)
            if not data:
                break
            text = data.decode(errors='replace')
            output_lines.append(text)
        except Exception:
            if chan.exit_status_ready():
                break

t = threading.Thread(target=collect_output, daemon=True)
t.start()

# Wait 6 seconds - by then vi_bayerdump should be active
print("[Waiting 6s - vi_bayerdump should be active by now]")
time.sleep(6)

print("\n=== MIPI state at 6s ===")
_, o = run("cat /proc/umap/mipi_rx 2>/dev/null")
print(o[:3000])  # limit output

print("\n=== VI dump attr at 6s ===")
_, o = run("cat /proc/umap/vi 2>/dev/null | grep -A3 'frame dump attr'")
print(o)

print("\n=== VI dev detect at 6s ===")
_, o = run("cat /proc/umap/vi 2>/dev/null | grep -A5 'dev detect info'")
print(o)

# Wait for binary to finish
time.sleep(10)
print("\n=== Process after 16s ===")
_, o = run(f"ps aux | grep {BINARY} | grep -v grep")
print("Process:", o.strip() or "(not running)")

print("\n=== All output ===")
print(''.join(output_lines))
b.close()
