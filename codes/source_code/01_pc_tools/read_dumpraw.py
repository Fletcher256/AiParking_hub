#!/usr/bin/env python3
"""Read full dtof_dumpraw.c to find UDP send logic and port."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
SRC = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src"

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)

    def run(cmd, timeout=15):
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out + err

    # Get line count
    wc = run(f"wc -l {SRC}/dtof/dtof_dumpraw.c")
    print(f"Line count: {wc.strip()}")

    # Read full file in chunks
    out = run(f"cat {SRC}/dtof/dtof_dumpraw.c", timeout=30)
    print(f"\n=== FULL dtof_dumpraw.c ({len(out)} bytes) ===")
    print(out)

    # Also search for anything with "port" or "send" or socket
    print("\n\n=== sample_dtof.c: server_ip usage ===")
    out2 = run(f"grep -n 'server_ip\\|udp\\|UDP\\|port\\|PORT\\|socket\\|send\\|SOCK' {SRC}/dtof/sample_dtof.c 2>/dev/null | head -40")
    print(out2)

    c.close()

if __name__ == "__main__":
    main()
