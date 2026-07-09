#!/usr/bin/env python3
"""
Update S90autorun with sleep 15 after dtof_init.sh, then reboot.
GS1860 needs ~10+ seconds after GPIO96 release before it responds to I2C.
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

    # Write updated S90autorun with sleep 15
    new_script = """#!/bin/sh
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20
cd /opt/sample/dtof
sh ./dtof_init.sh
sleep 15
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 > /tmp/dtof.log 2>&1 &
"""
    print("=== Writing S90autorun with sleep 15 ===")
    # Write via shell heredoc
    _, stdout, stderr = board.exec_command("cat > /etc/init.d/S90autorun << 'ENDOFSCRIPT'\n" + new_script + "ENDOFSCRIPT\n", timeout=10)
    stdout.read(); stderr.read()

    # Verify
    out = run(board, "cat /etc/init.d/S90autorun")
    print(out.strip())
    run(board, "chmod +x /etc/init.d/S90autorun")

    # Reboot
    print("\n=== Rebooting board ===")
    try:
        board.exec_command("reboot", timeout=3)
    except:
        pass
    board.close()
    print("Rebooting... waiting 60 seconds for board to come back...")

if __name__ == "__main__":
    main()
