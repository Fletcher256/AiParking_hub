"""查板子上 libc/libpthread 中问题符号的实际版本号."""
import paramiko

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect('192.168.137.2', username='root', password='ebaina',
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode()

# 找 libc/libpthread 路径
print("=== Dynamic libs ===")
print(run("ls /lib64/libc.so.6 /lib/libc.so.6 /lib64/libpthread* /lib/libpthread* 2>&1"))

# 查 __pthread_key_create 的版本
print("=== __pthread_key_create in libpthread ===")
print(run("readelf -sW /lib/libpthread-*.so 2>/dev/null | grep __pthread_key_create || "
          "nm -D /lib/libpthread.so.0 2>/dev/null | grep __pthread_key_create || "
          "strings /lib/libpthread.so.0 2>/dev/null | grep pthread_key"))

# 查全部版本节（.gnu.version_d）
print("=== libc.so.6 version definitions (partial) ===")
print(run("readelf -V /lib/libc.so.6 2>/dev/null | head -80"))

print("=== libpthread version definitions ===")
print(run("readelf -V /lib/libpthread.so.0 2>/dev/null | head -60"))

# 看 sample_dtof 用的是哪些版本
print("=== sample_dtof GLIBC requirements ===")
print(run("readelf -V /opt/sample/mipi_rgb_dtof_demo/sample_dtof 2>/dev/null | head -40"))

b.close()
