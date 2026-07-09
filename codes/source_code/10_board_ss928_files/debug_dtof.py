"""Check linear mode source and VI proc state."""
import paramiko

HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2';   USER_B  = 'root';  PASS_B  = 'ebaina'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

print("=== Find 'linear mode' in ALL sources ===")
rc, o, _ = run_vm(r"grep -rn 'linear mode\|WDR mode\|linear init' /home/ebaina/os08a20_dtof_build/ --include='*.c' 2>/dev/null | head -20")
print(o)

rc, o, _ = run_vm(r"grep -rn 'linear mode\|WDR mode' /home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp/sample/common/ --include='*.c' 2>/dev/null | head -20")
print(o)

rc, o, _ = run_vm(r"grep -rn 'linear mode\|WDR mode' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/ --include='*.c' 2>/dev/null | head -20")
print(o)

print("\n=== gs1860 cmos source - check I2C error printf stderr or stdout ===")
rc, o, _ = run_vm("grep -n 'I2C_WRITE error\|fprintf\|printf' /home/ebaina/os08a20_dtof_build/dtof/gs1860_cmos.c 2>/dev/null | head -30")
print(o or "(no gs1860_cmos.c in build)")

rc, o, _ = run_vm("find /home/ebaina/os08a20_dtof_build/dtof/ -name 'gs1860_cmos.c' 2>/dev/null")
print("gs1860_cmos.c location:", o.strip())

vm.close()
