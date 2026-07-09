#!/usr/bin/env python3
"""Extract UdpSendInit from libdepth_process.a and find UDP port."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
LIB = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/lib/linux/3rdparty/libdepth_process.a"

def connect_vm():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def connect_board():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=20):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()
    board = connect_board()

    # 1. List objects in libdepth_process.a
    print("=== Objects in libdepth_process.a ===")
    out = run(vm, f"ar t {LIB} 2>/dev/null")
    print(out.strip())

    # 2. strings on the entire library
    print("\n=== strings from libdepth_process.a ===")
    out = run(vm, f"strings {LIB} 2>/dev/null | head -100")
    print(out.strip())

    # 3. strings looking for port-like numbers
    print("\n=== strings - port numbers ===")
    out = run(vm, f"strings {LIB} 2>/dev/null | grep -E '^[0-9]{{4,5}}$'")
    print(out.strip())

    # 4. Extract the object with UdpSendInit and disassemble
    print("\n=== Extract UdpSend object and disassemble ===")
    out = run(vm, f"cd /tmp && ar x {LIB} 2>/dev/null; ls /tmp/*.o 2>/dev/null | head -10")
    print(out.strip())

    out = run(vm, f"nm /tmp/*.o 2>/dev/null | grep -i udpsend | head -10")
    print(out.strip())

    # 5. objdump on extracted object
    print("\n=== objdump -d for UdpSendInit ===")
    out = run(vm, "file=$(nm /tmp/*.o 2>/dev/null | grep -i 'UdpSendInit' | awk '{print $NF}' | head -1); "
                  "objfile=$(nm /tmp/*.o 2>/dev/null | grep -i 'UdpSendInit' | head -1); "
                  "echo 'looking for object...'; "
                  "for f in /tmp/*.o; do nm $f 2>/dev/null | grep -q 'UdpSendInit' && echo FOUND:$f && break; done",
              timeout=15)
    print(out.strip())

    # 6. Get the object file with UdpSendInit and disassemble
    print("\n=== Disassemble UdpSend object ===")
    out = run(vm, "for f in /tmp/*.o; do "
                  "if nm $f 2>/dev/null | grep -q 'UdpSendInit'; then "
                  "  echo 'Disassembling' $f; "
                  "  objdump -d $f 2>/dev/null | grep -A5 -B2 'htons\\|0x[0-9a-f]\\{3,4\\}' | head -60; "
                  "  echo '---'; "
                  "  strings $f 2>/dev/null; "
                  "fi; done", timeout=20)
    print(out.strip()[:5000])

    # 7. Board: strace the binary to see what sendto calls it makes (if strace available)
    print("\n=== Board: strace available? ===")
    out = run(board, "which strace 2>/dev/null || echo 'no strace'")
    print(out.strip())

    # 8. Board: /proc/net/udp with hex decoded
    print("\n=== Board: /proc/net/udp (raw) ===")
    out = run(board, "cat /proc/net/udp")
    print(out.strip())

    # 9. Board: try netstat with more options
    print("\n=== Board: netstat -an ===")
    out = run(board, "netstat -an 2>/dev/null | grep -E 'udp|UDP' | head -20")
    print(out.strip())

    vm.close()
    board.close()

if __name__ == "__main__":
    main()
