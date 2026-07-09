"""Check the original imx347 sample dtof init sequence and VB pool."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Look at the dtof init section in original imx347.c
print("=== Original imx347.c dtof section (lines 1050-1150) ===")
rc, o, _ = run_vm("sed -n '1050,1150p' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c")
print(o)

print("\n=== Original imx347_dtof_only dtof section (lines 1050-1150) ===")
rc, o, _ = run_vm("sed -n '1050,1150p' /home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp/sample/mipi_imx347_dtof_only/imx347.c")
print(o)

vm.close()
