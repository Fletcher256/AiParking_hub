"""Check dtof_init.sh and gs1860 I2C write mechanism."""
import paramiko

HOST_BOARD = '192.168.137.2'; USER_B = 'root'; PASS_B = 'ebaina'
HOST_VM    = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
SSH_OPTS   = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect(HOST_BOARD, username=USER_B, password=PASS_B, timeout=10, allow_agent=False, look_for_keys=False)

def run_b(cmd, timeout=15):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode() + err.read().decode()

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

print("=== dtof_init.sh ===")
rc, o = run_b("cat /opt/sample/dtof/dtof_init.sh")
print(o)

print("\n=== How gs1860_read_ini_file writes registers ===")
rc, o, _ = run_vm("grep -n 'gs1860_read_ini_file\|gs1860_write_register\|I2C_WRITE\|snsSensorI2cWrite\|bus_id' /home/ebaina/os08a20_dtof_build/dtof/gs1860_cmos.c 2>/dev/null | head -40")
print(o or "(no gs1860_cmos.c in build dtof)")

# Try to find the gs1860_cmos.c source
rc, o, _ = run_vm("find /home/ebaina -name 'gs1860_cmos.c' 2>/dev/null | head -10")
print("gs1860_cmos.c locations:", o.strip())

# Read the relevant section of gs1860_cmos.c
rc, o, _ = run_vm("sed -n '280,340p' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/gs1860_cmos.c 2>/dev/null")
print("\n=== gs1860_write_register from open_camera source ===")
print(o)

# Look for init order in original sample - is gs1860_read_ini_file after vi_start?
print("\n=== Full dtof init order in original (line 1070-1120) ===")
rc, o, _ = run_vm("sed -n '1070,1120p' /home/ebaina/Workspace/open_camera-master/mipi_rgb_dtof/code/mipi_imx347/imx347.c")
print(o)

# Check if dtof_init.sh runs binary first then ini
print("\n=== What the original sample_vio on board does (head -50 of binary strings?) ===")
rc, o = run_b("strings /opt/sample/mipi_imx347_dtof_only/sample_vio 2>/dev/null | grep -i 'ini\|i2c\|bus\|gs1860\|register' | head -30")
print(o)

b.close()
vm.close()
