#!/usr/bin/env python3
"""
Search sample_dtof binary for sockaddr_in patterns.
sockaddr_in starts with sin_family=AF_INET=2 (little-endian: 02 00)
followed by sin_port in network byte order (big-endian).
So we look for: 02 00 <port_hi> <port_lo>
"""
import paramiko, struct, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.137.2", username="root", password="ebaina",
          timeout=30, banner_timeout=30, auth_timeout=30)

_, out, _ = c.exec_command("cat /opt/sample/dtof/sample_dtof", timeout=60)
data = out.read()
c.close()
print(f"Binary: {len(data)} bytes")

# Search for AF_INET (2 as uint16 LE = \x02\x00) + port in NBO
# Pattern: 02 00 <port_byte_hi> <port_byte_lo>
hits = []
for i in range(len(data) - 3):
    if data[i] == 0x02 and data[i+1] == 0x00:
        port = (data[i+2] << 8) | data[i+3]
        if 1024 <= port <= 49151:
            hits.append((i, port, data[i:i+8].hex()))

print(f"\nFound {len(hits)} AF_INET+port patterns:")
port_counts = {}
for off, port, ctx in hits:
    port_counts[port] = port_counts.get(port, 0) + 1

for port, cnt in sorted(port_counts.items(), key=lambda x: -x[1]):
    print(f"  port {port:5d}  (0x{port:04x})  appears {cnt}x")

# Most likely candidates: ports appearing >= 2 times
common = [(p, c) for p, c in port_counts.items() if c >= 2]
if common:
    print("\nMost likely candidates (appearing >=2x):")
    for p, c in sorted(common, key=lambda x: -x[1]):
        print(f"  {p} ({p:04x}) x{c}")
