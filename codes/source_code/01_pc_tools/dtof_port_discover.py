#!/usr/bin/env python3
"""
Run on VM to discover the UDP port used by sample_dtof.
Listens on UDP ports 1024-49151 using a raw socket (requires root or cap_net_raw),
OR uses select() across multiple sockets on common ports.

Usage on VM:
  sudo python3 dtof_port_discover.py          # raw socket mode (recommended)
  python3 dtof_port_discover.py --multi       # multi-socket mode
"""

import socket, select, sys, struct, time

COMMON_PORTS = [7777, 8888, 9000, 7000, 6000, 5000, 8080, 8000, 4444, 3333,
                9999, 1234, 12345, 6666, 2333, 5555, 9876, 7788]

PACKET_MAGIC_SIZE = 4873  # expected dToF packet size


def raw_mode():
    """Sniff all UDP traffic on any port."""
    try:
        # Create raw UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
        sock.bind(('0.0.0.0', 0))
        sock.settimeout(30)
        print("Raw socket mode: waiting for any UDP packet (timeout 30s)...")
        print("Start 'sample_dtof <case> <vm_ip>' on the board now.\n")
        while True:
            data, addr = sock.recvfrom(65535)
            if len(data) < 8:
                continue
            # UDP header: src_port(2), dst_port(2), length(2), checksum(2)
            ip_header_len = (data[0] & 0xf) * 4
            udp_data = data[ip_header_len:]
            if len(udp_data) < 8:
                continue
            src_port = (udp_data[0] << 8) | udp_data[1]
            dst_port = (udp_data[2] << 8) | udp_data[3]
            udp_len  = (udp_data[4] << 8) | udp_data[5]
            payload  = udp_data[8:]
            src_ip   = f"{data[12]}.{data[13]}.{data[14]}.{data[15]}"
            print(f"UDP packet from {src_ip}:{src_port} -> :{dst_port}  len={udp_len-8}")
            if udp_len - 8 == PACKET_MAGIC_SIZE:
                print(f"  *** Matches dToF packet size! Use port {dst_port} ***")
                return dst_port
    except PermissionError:
        print("Raw socket requires root. Try: sudo python3 dtof_port_discover.py")
        return None


def multi_socket_mode():
    """Listen on all common ports simultaneously using select()."""
    sockets = {}
    for port in COMMON_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', port))
            s.setblocking(False)
            sockets[s] = port
        except OSError as e:
            print(f"  Could not bind port {port}: {e}")

    if not sockets:
        print("No ports could be bound.")
        return None

    print(f"Multi-socket mode: listening on {len(sockets)} ports: {sorted(sockets.values())}")
    print("Start 'sample_dtof <case> <vm_ip>' on the board now. (Timeout: 60s)\n")

    deadline = time.time() + 60
    while time.time() < deadline:
        readable, _, _ = select.select(list(sockets.keys()), [], [], 1.0)
        for s in readable:
            port = sockets[s]
            data, addr = s.recvfrom(8192)
            print(f"  Packet on port {port} from {addr[0]}:{addr[1]}  len={len(data)}")
            if len(data) == PACKET_MAGIC_SIZE:
                print(f"  *** Matches dToF packet size ({PACKET_MAGIC_SIZE}B)! Port = {port} ***")
                for s2 in sockets:
                    s2.close()
                return port
            else:
                print(f"  (size mismatch: got {len(data)}, expected {PACKET_MAGIC_SIZE})")

    print("Timeout. No dToF packet detected.")
    return None


if __name__ == '__main__':
    if '--multi' in sys.argv:
        port = multi_socket_mode()
    else:
        port = raw_mode()
    if port:
        print(f"\nDiscovered port: {port}")
        print(f"Update dtof_bridge with: --ros-args -p udp_port:={port}")
