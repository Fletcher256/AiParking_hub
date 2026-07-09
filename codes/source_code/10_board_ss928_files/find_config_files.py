"""找板子上的 ini 配置文件."""
import paramiko

b = paramiko.SSHClient()
b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
b.connect('192.168.137.2', username='root', password='ebaina',
          timeout=10, allow_agent=False, look_for_keys=False)

def run(cmd, timeout=10):
    _, out, err = b.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode() + err.read().decode()

# 列出 demo 目录
print("=== /opt/sample/mipi_rgb_dtof_demo/ ===")
print(run("ls -la /opt/sample/mipi_rgb_dtof_demo/"))

# 找 gs1860_register.ini
print("\n=== find gs1860_register.ini ===")
print(run("find /opt /usr /home -name 'gs1860_register.ini' 2>/dev/null"))

# 找 config_cfgaccess_hd.ini 或 param 目录
print("\n=== find config_cfgaccess*.ini ===")
print(run("find /opt -name '*.ini' 2>/dev/null | head -30"))

# 看 sample_dtof 所在目录是否有 param 文件夹
print("\n=== /opt/sample/ contents ===")
print(run("ls -la /opt/sample/"))

# 其他可能的目录
print("\n=== find /opt -name 'param' -type d ===")
print(run("find /opt -name 'param' -type d 2>/dev/null"))

b.close()
