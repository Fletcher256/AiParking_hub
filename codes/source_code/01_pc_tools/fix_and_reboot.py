#!/usr/bin/env python3
"""
Fix S90autorun (add sleep after dtof_init.sh) then reboot board.
Root cause: GS1860 needs time to boot after GPIO reset before binary's
VI init writes I2C registers. Without sleep, I2C writes succeed but
sensor isn't ready to stream MIPI data → vi_pipe 2 frame err forever.
"""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=15):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    board = connect()

    # 1. Show current S90autorun
    print("=== Current S90autorun ===")
    out = run(board, "cat /etc/init.d/S90autorun")
    print(out.strip())

    # 2. Write new S90autorun with sleep 3 after dtof_init.sh
    new_script = """#!/bin/sh
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20
cd /opt/sample/dtof
sh ./dtof_init.sh
sleep 3
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 > /tmp/dtof.log 2>&1 &
"""
    # Write the new script
    print("\n=== Writing new S90autorun (with sleep 3) ===")
    # Use printf to write without echo issues
    lines = new_script.replace('\n', '\\n').replace("'", "'\\''")
    out = run(board, f"printf '{lines}' > /etc/init.d/S90autorun && chmod +x /etc/init.d/S90autorun && echo 'OK'")
    print(out.strip())

    # 3. Verify new content
    print("\n=== New S90autorun ===")
    out = run(board, "cat /etc/init.d/S90autorun")
    print(out.strip())

    # 4. Reboot
    print("\n=== Rebooting board... ===")
    try:
        run(board, "reboot &", timeout=3)
    except:
        pass  # Connection will drop

    board.close()
    print("Reboot command sent. Waiting 30 seconds for board to come back up...")

if __name__ == "__main__":
    main()
