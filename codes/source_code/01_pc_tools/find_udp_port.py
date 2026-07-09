#!/usr/bin/env python3
"""
Find the hardcoded UDP port in sample_dtof by searching for htons() patterns.
On ARM64 little-endian, htons(port) is equivalent to byteswap16(port).
The port value appears as a constant in the instruction stream.
We look for common port values (stored as 16-bit big-endian in sin_port).
"""
import paramiko, struct, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.137.2", username="root", password="ebaina",
          timeout=30, banner_timeout=30, auth_timeout=30)

# Download the binary
_, out, _ = c.exec_command("cat /opt/sample/dtof/sample_dtof", timeout=60)
data = out.read()
c.close()

print(f"Binary size: {len(data)} bytes")

# Common UDP ports used in HiSilicon MPP samples
candidates = [7777, 8888, 9000, 7000, 6000, 5000, 1234, 9999, 8080, 8000, 4444, 3333]

# Also search for htons patterns: if port P is passed to htons on little-endian,
# the network byte-order result ((P>>8)|(P&0xff)<<8) appears in sin_port.
# More directly: search for MOVZ/MOVK instructions loading common port values in ARM64.
# ARM64 MOVZ: 0x52800000 | (imm16 << 5) | rd  (for 16-bit immediate)
# But let's just search for the raw bytes.

print("\nSearching for candidate port values as immediate operands...")
for port in candidates:
    # In network byte order (big-endian 16-bit): bytes are (port>>8, port&0xff)
    nb = struct.pack('>H', port)
    # In host byte order (little-endian): bytes are (port&0xff, port>>8)
    hb = struct.pack('<H', port)

    nb_count = data.count(nb)
    hb_count = data.count(hb)

    if nb_count > 0 or hb_count > 0:
        print(f"  Port {port:5d} (0x{port:04x}): NBO={nb.hex()} found {nb_count}x,  HBO={hb.hex()} found {hb_count}x")

# Search for all 2-byte patterns that could be ports (1024-49151) in NBO
print("\nAll 2-byte values in range 1024-49151 (network byte order) in binary:")
seen = {}
for i in range(0, len(data)-1):
    b0, b1 = data[i], data[i+1]
    port = (b0 << 8) | b1  # big-endian
    if 1024 <= port <= 49151:
        seen[port] = seen.get(port, 0) + 1

# Focus on values appearing a small number of times (likely a constant)
rare = [(p, c) for p, c in seen.items() if 1 <= c <= 5]
rare.sort(key=lambda x: x[1])
print("Ports appearing 1-5 times (likely hardcoded constants):")
for port, count in rare[:30]:
    print(f"  {port:5d} (0x{port:04x})  x{count}")
