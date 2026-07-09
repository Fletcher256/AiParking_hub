#!/usr/bin/env python3
"""Finalize: update S90autorun with log redirect, verify final state."""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out + err

def main():
    c = connect()

    # Show current S90autorun
    print("=== Current S90autorun ===")
    rc, cur = run(c, "cat /etc/init.d/S90autorun")
    print(cur)

    # Update S90autorun to add log redirect
    new_autorun = """#!/bin/sh
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20
cd /opt/sample/dtof
sh ./dtof_init.sh
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 > /tmp/dtof.log 2>&1 &
"""
    # Write new autorun
    run(c, f"cat > /etc/init.d/S90autorun << 'AUTORUN_EOF'\n{new_autorun}AUTORUN_EOF")
    # Actually write it properly
    import io

    c2 = connect()
    rc, out = run(c2, f"""cat > /etc/init.d/S90autorun << 'EOF'
#!/bin/sh
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20
cd /opt/sample/dtof
sh ./dtof_init.sh
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 > /tmp/dtof.log 2>&1 &
EOF
chmod +x /etc/init.d/S90autorun && echo 'OK'""")
    print(f"\n=== Update S90autorun: {out.strip()} ===")
    rc, new = run(c2, "cat /etc/init.d/S90autorun")
    print(new)
    c2.close()

    # Final state check
    print("\n=== Final system state ===")
    rc, vi = run(c, "cat /proc/umap/vi | grep -A3 'vi pipe status'")
    print(f"VI:\n{vi}")

    rc, venc = run(c, "cat /proc/umap/venc | grep 'sequence\\|frame_rate' | head -4 2>/dev/null")
    print(f"VENC:\n{venc}")

    rc, detect = run(c, "cat /proc/umap/mipi_rx | grep -A6 'detect info'")
    print(f"MIPI detect:\n{detect}")

    rc, reg = run(c, "i2ctransfer -y 5 w2@0x36 0x01 0x00 r1 2>/dev/null")
    print(f"OS08A20 0x0100: {reg.strip()}")

    rc, ps = run(c, "ps | grep sample_dtof | grep -v grep")
    print(f"Process: {ps.strip()}")

    c.close()

if __name__ == "__main__":
    main()
