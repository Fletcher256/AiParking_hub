"""Check VB pool config in original imx347 sample and GS1860 sensor size."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Check VB config in original imx347 sample
print("=== VB config in original imx347.c ===")
rc, o, _ = run_vm("grep -n 'vb_cfg\|blk_size\|blk_cnt\|VB_\|vb_pool\|pool' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c | head -60")
print(o)

print("\n=== GS1860 size in sample_comm_vi.c ===")
rc, o, _ = run_vm("grep -n 'GS1860\|gs1860\|1M_30FPS' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/common/sample_comm_vi.c | head -30")
print(o)

# Also check SDK sample_comm_vi.c
print("\n=== GS1860 size in SDK sample_comm_vi.c ===")
rc, o, _ = run_vm("grep -n 'GS1860\|gs1860\|1M_30FPS' /home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp/sample/common/sample_comm_vi.c | head -30")
print(o)

# Check what size GS1860 uses
print("\n=== Sample sizes for sensors ===")
rc, o, _ = run_vm("grep -A3 'GS1860' /home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp/sample/common/sample_comm_vi.c | head -20")
print(o)

# Check original imx347_dtof_only VB setup
print("\n=== imx347_dtof_only VB pool setup ===")
rc, o, _ = run_vm("grep -n 'sample_vi_get_default_vb_config\|blk_size\|blk_cnt\|pool\|sys_init' /home/ebaina/Workspace/SS928V100_SDK_V2.0.2.2/smp/a55_linux/mpp/sample/mipi_imx347_dtof_only/imx347.c | head -30")
print(o)

vm.close()
