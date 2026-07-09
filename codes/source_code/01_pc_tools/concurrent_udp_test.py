#!/usr/bin/env python3
"""
Start binary on board AND UDP listener on VM simultaneously.
The board binary is already running from S90autorun (cold boot).
We just do SIGTERM -> clean exit -> warm restart -> listen for UDP concurrently.
"""
import paramiko, time, threading

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"

def connect(host, user, pw):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=30)
    return c

def run(c, cmd, timeout=60):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)
    vm = connect(VM_HOST, VM_USER, VM_PASS)

    # Check current state
    print("=== Current binary state ===")
    ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh")
    print(ps.strip() or "not running")

    log = run(board, "cat /tmp/dtof.log 2>/dev/null | wc -l")
    print(f"Current log lines: {log.strip()}")

    # SIGTERM -> wait for clean exit
    print("\n=== SIGTERM clean shutdown ===")
    run(board, "pkill -TERM sample_dtof 2>/dev/null")
    for i in range(8):
        time.sleep(2)
        ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        if not ps:
            print(f"  Exited cleanly after {(i+1)*2}s")
            break
        print(f"  Still running ({(i+1)*2}s)...")
    else:
        print("  Force kill")
        run(board, "pkill -KILL sample_dtof 2>/dev/null")
        time.sleep(2)

    # Start UDP listener on VM in background thread
    udp_result = []
    def listen_udp():
        udp_script = """
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 2368))
s.settimeout(1)
count = 0; sizes = []; first_time = None
t0 = time.time()
while time.time()-t0 < 20:
    try:
        data, addr = s.recvfrom(65535)
        if first_time is None:
            first_time = time.time() - t0
        count += 1; sizes.append(len(data))
        if count <= 3:
            print(f'PKT {count}: {len(data)} bytes from {addr[0]}:{addr[1]}')
    except: pass
s.close()
if count:
    print(f'SUCCESS: {count} pkts in 20s, avg {sum(sizes)//len(sizes)} bytes, first at t+{first_time:.1f}s')
else:
    print('NO DATA: 0 packets on port 2368 in 20s')
"""
        sftp = vm.open_sftp()
        with sftp.open('/tmp/udp_listen.py', 'w') as f:
            f.write(udp_script)
        sftp.close()
        result = run(vm, "python3 /tmp/udp_listen.py", timeout=25)
        udp_result.append(result)

    # Start UDP listener thread
    t = threading.Thread(target=listen_udp)
    t.start()

    # Small delay then start binary
    time.sleep(1)
    print("\n=== Warm restart binary ===")
    run(board, "rm -f /tmp/dtof.log")
    board.exec_command(
        "cd /opt/sample/dtof && "
        "sleep 7200 | ./sample_dtof 3 192.168.137.100 > /tmp/dtof.log 2>&1 &"
    )
    print("Binary started. UDP listener running for 20s...")

    # Wait for UDP listener to finish
    t.join()
    print("\n=== UDP Result ===")
    print(udp_result[0] if udp_result else "no result")

    # Check final log state
    print("\n=== Final dtof.log ===")
    log = run(board, "cat /tmp/dtof.log 2>/dev/null")
    for l in log.split("\n"):
        if "I2C_WRITE" not in l and l.strip():
            print(l)
    print(f"\nI2C errors: {log.count('I2C_WRITE error')}")
    print(f"DtofInit success: {'DtofInit success' in log}")
    print(f"Frame errors: {log.count('frame err')}")

    board.close()
    vm.close()

if __name__ == "__main__":
    main()
