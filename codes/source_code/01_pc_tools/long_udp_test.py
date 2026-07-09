#!/usr/bin/env python3
"""Listen for UDP on VM port 2368 for 60s while polling board log."""
import paramiko, time, threading

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"

def connect(h, u, p):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(h, username=u, password=p, timeout=30)
    return c

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

UDP_SCRIPT = """
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 2368))
s.settimeout(1)
count = 0
sizes = []
first_t = None
t0 = time.time()
while time.time() - t0 < 60:
    try:
        data, addr = s.recvfrom(65535)
        if first_t is None:
            first_t = time.time() - t0
        count += 1
        sizes.append(len(data))
        if count <= 5:
            elapsed = time.time() - t0
            print("PKT %d: %dB from %s:%d t+%.1fs" % (count, len(data), addr[0], addr[1], elapsed))
    except:
        pass
s.close()
if count:
    avg = sum(sizes) // len(sizes)
    print("SUCCESS: %d pkts, avg %dB, first at t+%.1fs" % (count, avg, first_t))
else:
    print("NO DATA: 0 packets in 60s on port 2368")
"""

def main():
    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)
    vm = connect(VM_HOST, VM_USER, VM_PASS)

    print("=== Binary state ===")
    print(run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip())

    # Write UDP script to VM
    sftp = vm.open_sftp()
    with sftp.open("/tmp/udp_listen60.py", "w") as f:
        f.write(UDP_SCRIPT)
    sftp.close()

    # Start UDP listener in background thread
    result = []
    def listen_thread():
        out = run(vm, "python3 /tmp/udp_listen60.py", timeout=70)
        result.append(out)

    t = threading.Thread(target=listen_thread)
    t.start()
    print("UDP listener started on VM port 2368 (60s)...")

    # Poll board log every 10s
    for i in range(6):
        time.sleep(10)
        log = run(board, "cat /tmp/dtof.log 2>/dev/null")
        i2c = log.count("I2C_WRITE error")
        dtof_ok = "DtofInit success" in log
        frame_err = log.count("frame err")
        ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        print("t+%ds | I2C=%d | DtofInit=%s | FrameErr=%d | %s" % (
            (i+1)*10, i2c, dtof_ok, frame_err, ps[:50]))

    t.join()
    print("\n=== UDP Result ===")
    print(result[0] if result else "no result")

    # Final log check
    log = run(board, "cat /tmp/dtof.log 2>/dev/null")
    print("\n=== Key log messages ===")
    for l in log.split("\n"):
        if "I2C_WRITE" not in l and l.strip():
            print(l)

    board.close()
    vm.close()

if __name__ == "__main__":
    main()
