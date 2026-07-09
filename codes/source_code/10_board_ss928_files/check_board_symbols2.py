"""用 nm/objdump/strings 查板子符号版本."""
import paramiko

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect('192.168.137.2', username='root', password='ebaina',
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode() + err.read().decode()

# 可用工具
print("=== Tools ===")
print(run("which nm objdump strings readelf 2>&1"))

# 用 nm 查 libpthread
print("=== nm -D libpthread | grep key ===")
print(run("nm -D /lib64/libpthread.so.0 2>&1 | grep -i 'key_create'"))

# 用 nm 查 libc
print("=== nm -D libc | grep pthread_key ===")
print(run("nm -D /lib64/libc.so.6 2>&1 | grep 'pthread_key'"))

# 查 libpthread 里所有 GLIBC_2.xx 版本标记
print("=== GLIBC versions in libpthread (strings) ===")
print(run("strings /lib64/libpthread.so.0 | grep 'GLIBC_' | sort -u"))

# 查 libc 提供的所有版本标记
print("=== GLIBC versions in libc.so.6 (strings) ===")
print(run("strings /lib64/libc.so.6 | grep 'GLIBC_' | sort -u"))

# 查 sample_dtof 用的版本
print("=== sample_dtof GLIBC strings ===")
print(run("strings /opt/sample/mipi_rgb_dtof_demo/sample_dtof | grep 'GLIBC_' | sort -u"))

b.close()
