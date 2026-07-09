#!/usr/bin/env python3
"""Find the cross-compiler and build environment on VM."""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    print("=== Find aarch64 cross-compiler ===")
    rc, out = run(c, "find / -name 'aarch64*gcc' -type f 2>/dev/null | head -10")
    print(out.strip())

    print("\n=== PATH env ===")
    rc, path = run(c, "echo $PATH; which aarch64-linux-gnu-gcc 2>/dev/null || echo 'not in PATH'")
    print(path.strip())

    print("\n=== Check /opt for toolchains ===")
    rc, opt = run(c, "ls /opt/ 2>/dev/null; ls /usr/local/bin/aarch64* 2>/dev/null | head -5")
    print(opt.strip())

    print("\n=== Check Makefile.param for toolchain path ===")
    rc, mp = run(c, "cat /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/Makefile.param 2>/dev/null | head -40")
    print(mp)

    print("\n=== Check if there's a setup/env script ===")
    rc, env = run(c, "find /home/ebaina/ZZIP -name '*.sh' -maxdepth 2 2>/dev/null | head -10; "
                     "ls /home/ebaina/ZZIP/ 2>/dev/null")
    print(env.strip())

    c.close()

if __name__ == "__main__":
    main()
