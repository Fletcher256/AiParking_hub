#!/usr/bin/env python3
"""Find bytes near the hardcoded IP string '192.168.137.2' to find the associated port."""
import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.137.2", username="root", password="ebaina",
          timeout=30, banner_timeout=30, auth_timeout=30)

_, out, _ = c.exec_command("cat /opt/sample/dtof/sample_dtof", timeout=60)
data = out.read()
c.close()

ip_bytes = b"192.168.137.2"
pos = 0
while True:
    idx = data.find(ip_bytes, pos)
    if idx == -1:
        break
    # Print context: 64 bytes before and after
    start = max(0, idx - 64)
    end   = min(len(data), idx + len(ip_bytes) + 64)
    ctx   = data[start:end]
    print(f"\n--- Found at offset 0x{idx:x} ---")
    # Print as hex dump
    for i in range(0, len(ctx), 16):
        chunk = ctx[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        asc_part = "".join(chr(b) if 0x20 <= b < 0x7f else '.' for b in chunk)
        print(f"  {start+i:08x}:  {hex_part:<47}  |{asc_part}|")
    pos = idx + 1

# Also search for port 7777 as network byte order (1e 61) near any instruction
print("\n\nSearching for port 7777 in NBO (1e 61) context:")
p = b"\x1e\x61"
pos = 0
count = 0
while count < 10:
    idx = data.find(p, pos)
    if idx == -1:
        break
    start = max(0, idx-8)
    end = min(len(data), idx+16)
    chunk = data[start:end]
    hex_part = " ".join(f"{b:02x}" for b in chunk)
    print(f"  0x{idx:x}: {hex_part}")
    pos = idx + 1
    count += 1
