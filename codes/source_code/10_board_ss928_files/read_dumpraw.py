"""Read dtof_dumpraw.c from VM build dir."""
import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'

vm = paramiko.SSHClient()
vm.set_missing_host_key_policy(paramiko.AutoAddPolicy())
vm.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=30):
    _, out, err = vm.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Read the vi_bayerdump function from line 460 onwards
rc, o, _ = run_vm("sed -n '460,600p' /home/ebaina/os08a20_dtof_build/dtof_dumpraw.c")
print(o)

vm.close()
