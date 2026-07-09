#!/usr/bin/env python3
"""
End-to-end test:
1. Start dtof_bridge node on VM in background
2. Send 10 simulated dToF packets from PC to VM:7777
3. Query /dtof/depth topic on VM to confirm messages received
4. Stop the bridge
"""
import paramiko, socket, struct, time, math, sys, threading

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
PORT    = 7777

PIXELS_H, PIXELS_W = 30, 40
PIXELS   = PIXELS_H * PIXELS_W
FX, FY   = 30.0, 30.0
CX, CY   = 19.5, 14.5

HEAD_FMT  = '<hh Ih II hhh B 12f'
PIXEL_FMT = '<hBB'
HEAD_SIZE = struct.calcsize(HEAD_FMT)


def make_packet(seq):
    t = time.time()
    ts_sec, ts_nsec = int(t), int((t % 1) * 1e9)
    head = struct.pack(HEAD_FMT,
        0, seq & 0x7fff, 0, PIXELS, ts_sec, ts_nsec,
        PIXELS_W, PIXELS_H, 5, 1,
        FX, FY, CX, CY, 0, 0, 0, 0, 0, 0, 0, 0)
    pixels = b""
    for i in range(PIXELS):
        v, u = divmod(i, PIXELS_W)
        r = math.sqrt((u - CX)**2 + (v - CY)**2)
        d = int(1200 + 300 * math.exp(-r*r/30))
        pixels += struct.pack(PIXEL_FMT, d, 200, 0)
    return head + pixels


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=15)
    return c


def run(client, cmd, timeout=30):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    return rc, o, e


def main():
    print("=== dToF Bridge End-to-End Test ===\n")

    client = connect()

    # Kill any existing bridge instances
    run(client, "pkill -f dtof_bridge 2>/dev/null; sleep 0.5")

    # Start bridge in background, log to file
    bridge_cmd = (
        "source /opt/ros/humble/setup.bash && "
        f"export PYTHONPATH=/home/ebaina/parking_ws/src/parking_bridge:$PYTHONPATH && "
        f"python3 /home/ebaina/parking_ws/src/parking_bridge/parking_bridge/dtof_bridge.py "
        f"--ros-args -p udp_port:={PORT} > /tmp/dtof_bridge.log 2>&1"
    )
    client.exec_command(f"bash -c '{bridge_cmd}' &", timeout=5)

    print(f"Bridge started on VM, UDP port {PORT}")
    print("Waiting 2s for bridge to initialize...")
    time.sleep(2)

    # Send 10 test packets from PC -> VM
    print(f"\nSending 10 test packets to {VM_HOST}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(10):
        pkt = make_packet(i)
        sock.sendto(pkt, (VM_HOST, PORT))
        print(f"  Sent frame {i:2d}  ({len(pkt)} bytes)")
        time.sleep(0.1)
    sock.close()

    time.sleep(1)

    # Check bridge log
    rc, log, _ = run(client, "cat /tmp/dtof_bridge.log")
    print(f"\n--- Bridge log ---")
    print(log[:2000] if log else "(empty)")

    # Check ROS2 topics
    print("\n--- ROS2 topic check ---")
    rc, out, err = run(client,
        "bash -c 'source /opt/ros/humble/setup.bash && "
        "export PYTHONPATH=/home/ebaina/parking_ws/src/parking_bridge:$PYTHONPATH && "
        "timeout 3 ros2 topic list 2>/dev/null'",
        timeout=10)
    print("Topics:", out.strip() if out else "(none)")

    rc, out, err = run(client,
        "bash -c 'source /opt/ros/humble/setup.bash && "
        "export PYTHONPATH=/home/ebaina/parking_ws/src/parking_bridge:$PYTHONPATH && "
        "timeout 4 ros2 topic echo /dtof/depth --once 2>/dev/null | head -20'",
        timeout=10)
    if out:
        print("Depth topic data received!")
        print(out[:500])
    else:
        print("No data on /dtof/depth (bridge might need ROS daemon or more time)")

    # Cleanup
    run(client, "pkill -f dtof_bridge 2>/dev/null")
    client.close()
    print("\n=== Test complete ===")


if __name__ == "__main__":
    main()
