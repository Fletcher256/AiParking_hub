#!/usr/bin/env python3
"""Update S90autorun on board and reboot."""
import paramiko, sys, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

S90_CONTENT = b"""#!/bin/sh

# Static IP for host PC (192.168.137.x subnet)
ip addr add 192.168.137.2/24 dev eth0 2>/dev/null

# Load kernel modules
cd /opt/ko
./load_ss928v100 -i -sensor0 os08a20

# GPIO/PWM init for GS1860 dToF
cd /opt/sample/dtof
sh ./dtof_init.sh

# Start combined camera (OS08A20 sensor0) + dToF (GS1860 sensor2) mode
sleep 7200 | ./sample_dtof_os08a20 3 192.168.137.100 &
"""

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS,
                   timeout=30, banner_timeout=30, auth_timeout=30)
    return client

def run(client, cmd, timeout=15):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err

def main():
    c = connect()

    # Show current S90autorun
    rc, out, err = run(c, "cat /etc/init.d/S90autorun")
    print("=== Current S90autorun ===")
    print(out)

    # Upload new S90autorun
    print("=== Uploading new S90autorun ===")
    chan = c.get_transport().open_session()
    chan.exec_command("cat > /etc/init.d/S90autorun")
    chan.sendall(S90_CONTENT)
    chan.shutdown_write()
    upload_rc = chan.recv_exit_status()
    print(f"Upload rc={upload_rc}")

    # chmod +x and verify
    rc, out, err = run(c, "chmod +x /etc/init.d/S90autorun && cat /etc/init.d/S90autorun")
    print("=== New S90autorun ===")
    print(out)
    c.close()

    print("=== S90autorun updated. Board needs reboot for changes to take effect. ===")
    print("Please reboot the board manually.")

if __name__ == "__main__":
    main()
