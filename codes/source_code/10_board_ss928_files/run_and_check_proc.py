"""Start binary, wait a bit, then check MIPI and VI proc state while running."""
import paramiko, time, sys, threading

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

# Kill any existing
run("pkill -9 -f sample 2>/dev/null; sleep 1")

# Start binary in background
print(f"Starting {BINARY} in background...")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command(f"cd {DEST_DIR} && ./{BINARY} 1 192.168.137.1")

# Collect output in separate thread
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
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            if chan.exit_status_ready():
                break

t = threading.Thread(target=collect_output, daemon=True)
t.start()

# Wait for binary to initialize (7 seconds should be enough past the 4s vi_bayerdump timeout)
print("\n[Waiting 7s for binary to initialize...]")
time.sleep(7)

# Check proc files while binary might still be running
print("\n\n=== /proc/umap/mipi_rx ===")
_, o = run("cat /proc/umap/mipi_rx 2>/dev/null | head -60")
print(o)

print("\n=== /proc/umap/vi (pipe status) ===")
_, o = run("cat /proc/umap/vi 2>/dev/null | head -80")
print(o or "(vi proc not found)")

print("\n=== Check process state ===")
_, o = run(f"ps aux | grep {BINARY} | grep -v grep")
print("Process:", o.strip() or "(not running)")

# Wait for output thread to complete
time.sleep(3)
print("\n=== Full captured output ===")
print(''.join(output_lines))

b.close()
