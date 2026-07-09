"""Read DumpLinearBayer and GetDumpPipe from dtof_dumpraw.c."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Count total lines
rc, o, _ = run_vm("wc -l /home/ebaina/os08a20_dtof_build/dtof_dumpraw.c")
print("Total lines:", o.strip())

# Read first 460 lines (DumpLinearBayer and GetDumpPipe should be there)
print("\n=== Lines 1-200 ===")
rc, o, _ = run_vm("sed -n '1,200p' /home/ebaina/os08a20_dtof_build/dtof_dumpraw.c")
print(o)

vm.close()
