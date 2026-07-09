"""SSH to board via VM jump host using paramiko."""
import paramiko, socket, time, sys

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';  USER_B  = 'root';  PASS_B  = 'ebaina'

SSH_OPTS = dict(username=USER_B, password=PASS_B,
                timeout=15, allow_agent=False, look_for_keys=False)

def board_client():
    """Return paramiko SSHClient connected to board via VM jump."""
    jump = paramiko.SSHClient()
    jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    jump.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

    transport = jump.get_transport()
    dest_addr  = (HOST_BOARD, 22)
    local_addr = ('127.0.0.1', 0)
    chan = transport.open_channel('direct-tcpip', dest_addr, local_addr)

    b = paramiko.SSHClient()
    b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    b.connect(HOST_BOARD, sock=chan, **SSH_OPTS)
    return jump, b

def run(b, cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

jump, b = board_client()
print("=== Connected to board ===")

# 1. Check what's running
rc, o, _ = run(b, "ps aux | grep -E 'sample_vio|sample_dtof|sample_os08' | grep -v grep")
print("Running processes:\n", o.strip() or "(none)")

# 2. Kill any conflicting processes
run(b, "pkill -f sample_vio 2>/dev/null; pkill -f sample_dtof 2>/dev/null; sleep 1")
print("Killed old processes")

# 3. Check ko files
rc, o, _ = run(b, "lsmod | grep -E 'ot_isp|ot_vi|ot_mipi'")
print("KO loaded:\n", o.strip() or "(none)")

# 4. Check binary exists
rc, o, _ = run(b, "ls -lh /opt/sample/mipi_rgb_dtof_demo/sample_os08a20_dtof")
print("Binary:", o.strip())

# 5. Check dtof demo dir contents
rc, o, _ = run(b, "ls /opt/sample/mipi_rgb_dtof_demo/")
print("Demo dir:\n", o.strip())

b.close(); jump.close()
