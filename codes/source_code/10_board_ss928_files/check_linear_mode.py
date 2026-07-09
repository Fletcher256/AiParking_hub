"""Find where 'linear mode' is printed and check MIPI combo dev config."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2'; USER_B = 'root'; PASS_B = 'ebaina'
SSH_OPTS = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

print("=== Where is 'linear mode' printed? ===")
rc, o, _ = run_vm("grep -rn 'linear mode' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/ --include='*.c' | head -20")
print(o)

rc, o, _ = run_vm("grep -rn 'linear mode' /home/ebaina/os08a20_dtof_build/ --include='*.c' | head -20")
print(o)

print("\n=== sample_comm_vi_start_vi calls flow ===")
rc, o, _ = run_vm("grep -n 'sample_comm_vi_start_vi\|linear mode\|WDR mode' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/common/sample_comm_vi.c | head -40")
print(o)

print("\n=== Check original imx347 VB pool actual sizes printed ===")
# Try to check board for evidence of running the pre-built binary
b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B, timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode() + err.read().decode()

print(run_b("ls /opt/sample/mipi_imx347_dtof_demo/"))
print(run_b("ls /opt/sample/mipi_imx347_dtof_only/ 2>/dev/null || echo '(not found)'"))

print("\n=== Check mipi rx combo dev on board ===")
print(run_b("cat /proc/umap/mipi_rx 2>/dev/null | head -30 || echo 'no mipi_rx proc'"))

b.close()
vm.close()
