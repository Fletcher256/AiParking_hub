"""Run sample_os08a20_dtof on board directly via paramiko."""
import paramiko, time, sys

HOST_BOARD = '192.168.137.2'
USER_B = 'root'
PASS_B = 'ebaina'

def board_client():
    b = paramiko.SSHClient()
    b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    b.connect(HOST_BOARD, username=USER_B, password=PASS_B,
              timeout=10, allow_agent=False, look_for_keys=False)
    return b

def run(b, cmd, timeout=15):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

b = board_client()
print("=== Connected to board ===")

# Check current state
rc, o, _ = run(b, "ps aux | grep -E 'sample_vio|sample_dtof|sample_os08a20' | grep -v grep")
print("Running processes:\n", o.strip() or "(none)")

rc, o, _ = run(b, "lsmod | grep -E 'ot_isp|ot_vi|ot_mipi'")
print("KO loaded:\n", o.strip() or "(none)")

# Check if init script exists
rc, o, _ = run(b, "ls /opt/sample/mipi_rgb_dtof_demo/")
print("Demo dir:", o.strip())

# Run the binary in background, capture first 8 seconds of output
print("\n=== Starting sample_os08a20_dtof ===")
chan = b.get_transport().open_session()
chan.set_combine_stderr(True)
chan.exec_command("cd /opt/sample/mipi_rgb_dtof_demo && ./sample_os08a20_dtof 1 192.168.137.100")

# Read output for 8 seconds
start = time.time()
output = b""
chan.settimeout(1.0)
while time.time() - start < 8:
    try:
        data = chan.recv(4096)
        if not data:
            print("Process exited early")
            break
        output += data
        # Print incrementally
        sys.stdout.write(data.decode(errors='replace'))
        sys.stdout.flush()
    except Exception:
        pass

print("\n\n=== After 8s: checking processes ===")
rc, o, _ = run(b, "ps aux | grep sample_os08a20 | grep -v grep")
print(o.strip() or "(not running)")

# Check for FIFO/stream output
rc, o, _ = run(b, "ls -la /tmp/stream_chn0.h265 2>/dev/null || echo 'no stream file'")
print("Stream file:", o.strip())

b.close()
print("Done.")
