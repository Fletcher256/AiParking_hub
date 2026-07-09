#!/usr/bin/env python3
"""Poll board SSH until reachable, then exit 0."""
import paramiko, sys, time

HOST = "192.168.137.2"
USER = "root"
PASS = "ebaina"
ATTEMPTS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
INTERVAL = int(sys.argv[2]) if len(sys.argv) > 2 else 10

for i in range(1, ATTEMPTS + 1):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(HOST, username=USER, password=PASS, timeout=8, banner_timeout=8, auth_timeout=8)
        _, stdout, _ = client.exec_command("echo OK", timeout=5)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        client.close()
        if "OK" in out:
            print(f"Board reachable after attempt {i}")
            sys.exit(0)
    except Exception as e:
        print(f"Attempt {i}/{ATTEMPTS}: {e}")
    if i < ATTEMPTS:
        time.sleep(INTERVAL)

print("Board not reachable after all attempts")
sys.exit(1)
