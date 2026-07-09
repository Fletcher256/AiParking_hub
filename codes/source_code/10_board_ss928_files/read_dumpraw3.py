"""Read DumpLinearBayer and rest of dtof_dumpraw.c."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

print("=== Lines 200-460 (DumpLinearBayer etc) ===")
rc, o, _ = run_vm("sed -n '200,460p' /home/ebaina/os08a20_dtof_build/dtof_dumpraw.c")
print(o)

vm.close()
