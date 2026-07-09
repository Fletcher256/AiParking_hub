"""Find vi_bayerdump source on VM and check dtof source on board."""
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

print("=== 1. Find vi_bayerdump in VM sources ===")
rc, o, _ = run_vm("grep -r 'vi_bayerdump' /home/ebaina --include='*.c' --include='*.h' -l 2>/dev/null | head -20")
print(o.strip() or "(not found)")

print("\n=== 2. Find vi_bayerdump definition ===")
rc, o, _ = run_vm("grep -r 'vi_bayerdump' /home/ebaina --include='*.c' -n 2>/dev/null | head -40")
print(o.strip() or "(not found)")

print("\n=== 3. Find vi_bayerdump in dtof sources ===")
rc, o, _ = run_vm("find /home/ebaina -name '*.c' | xargs grep -l 'vi_bayerdump' 2>/dev/null | head -10")
print(o.strip() or "(not found)")

print("\n=== 4. Check original dtof sample source ===")
rc, o, _ = run_vm("find /home/ebaina -path '*/dtof*' -name '*.c' 2>/dev/null | head -20")
print(o.strip() or "(not found)")

print("\n=== 5. Check build dir for dtof related C files ===")
rc, o, _ = run_vm("ls /home/ebaina/os08a20_dtof_build/ 2>/dev/null")
print(o.strip())

print("\n=== 6. Find where vi_bayerdump is declared (headers) ===")
rc, o, _ = run_vm("grep -r 'vi_bayerdump' /home/ebaina --include='*.h' -n 2>/dev/null | head -20")
print(o.strip() or "(not found in headers)")

# Also check SDK path
print("\n=== 7. SDK DTOF sources ===")
rc, o, _ = run_vm("find /home/ebaina/Workspace -name '*.c' -path '*dtof*' 2>/dev/null | head -20")
print(o.strip() or "(not found)")

rc, o, _ = run_vm("grep -r 'vi_bayerdump' /home/ebaina/Workspace --include='*.c' --include='*.h' -l 2>/dev/null | head -10")
print("vi_bayerdump in SDK:", o.strip() or "(not found)")

vm.close()
