#!/usr/bin/env python3
"""
Proper warm start sequence:
1. Reboot board -> S90autorun starts binary (cold boot, 92 I2C errors expected)
2. Wait for binary to be stable
3. SIGTERM -> wait for clean ISP shutdown
4. Restart binary (true warm restart: ISP cleaned, GS1860 state preserved)
5. Verify UDP on VM port 2368
"""
import paramiko, time

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"

def connect(host, user, pw, retries=20):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for i in range(retries):
        try:
            c.connect(host, username=user, password=pw, timeout=10)
            return c
        except:
            time.sleep(5)
    raise Exception(f"Cannot connect to {host}")

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    # Step 1: Reboot
    print("=== Step 1: Reboot board ===")
    try:
        b = connect(BOARD_HOST, BOARD_USER, BOARD_PASS, retries=3)
        b.exec_command("reboot", timeout=5)
        b.close()
    except: pass
    print("Rebooting... waiting 50s")
    time.sleep(50)

    # Step 2: Wait for S90autorun binary to start and stabilize
    print("\n=== Step 2: Wait for cold boot binary to stabilize ===")
    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)

    for i in range(10):
        time.sleep(5)
        ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        log = run(board, "cat /tmp/dtof.log 2>/dev/null")
        dtof_ok = "DtofInit success" in log
        frame_err = "frame err" in log
        i2c = log.count("I2C_WRITE error")
        print(f"  t+{(i+1)*5}s | I2C={i2c} | DtofInit={dtof_ok} | FrameErr={frame_err} | {ps[:50]}")
        if dtof_ok:
            print("  -> Cold boot binary stable!")
            break

    print("\n=== Step 3: SIGTERM -> clean ISP shutdown ===")
    run(board, "pkill -TERM sample_dtof 2>/dev/null")
    # Wait for clean exit (ISP cleanup takes a few seconds)
    for i in range(6):
        time.sleep(3)
        ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        if not ps or "gone" in ps:
            print(f"  Binary exited cleanly after {(i+1)*3}s")
            break
        print(f"  Still running after {(i+1)*3}s: {ps[:60]}")
    else:
        print("  WARNING: Did not exit cleanly, trying SIGKILL")
        run(board, "pkill -KILL sample_dtof 2>/dev/null")
        time.sleep(3)

    # Step 4: Restart binary (warm restart)
    print("\n=== Step 4: Warm restart ===")
    run(board, "rm -f /tmp/dtof.log")
    board.exec_command(
        "cd /opt/sample/dtof && "
        "sleep 7200 | ./sample_dtof 3 192.168.137.100 > /tmp/dtof.log 2>&1 &"
    )

    print("Polling log...")
    for i in range(8):
        time.sleep(5)
        log = run(board, "cat /tmp/dtof.log 2>/dev/null")
        i2c = log.count("I2C_WRITE error")
        dtof_ok = "DtofInit success" in log
        frame_err = "frame err" in log
        vb_fail = "vb_set_conf failed" in log or "ISP_MemInit failed" in log
        ps = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        print(f"  t+{(i+1)*5}s | I2C={i2c} | DtofInit={dtof_ok} | FrameErr={frame_err} | VBfail={vb_fail} | {ps[:40]}")
        if dtof_ok or vb_fail:
            break

    # Show key log messages
    log = run(board, "cat /tmp/dtof.log 2>/dev/null")
    print("\n=== dtof.log (key messages only) ===")
    for l in log.split("\n"):
        if "I2C_WRITE" not in l and l.strip():
            print(l)

    board.close()

    # Step 5: UDP test
    print("\n=== Step 5: UDP listener on VM port 2368 (10s) ===")
    vm = connect(VM_HOST, VM_USER, VM_PASS)
    udp_script = """
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 2368))
s.settimeout(2)
count = 0; sizes = []
t0 = time.time()
while time.time()-t0 < 10:
    try:
        data, addr = s.recvfrom(65535)
        count += 1; sizes.append(len(data))
        if count <= 5:
            print(f'  PKT {count}: {len(data)} bytes from {addr[0]}:{addr[1]}')
    except: pass
s.close()
if count:
    print(f'SUCCESS: {count} packets in 10s, avg {sum(sizes)//len(sizes)} bytes each')
else:
    print('NO DATA: 0 packets received on port 2368')
"""
    sftp = vm.open_sftp()
    with sftp.open('/tmp/udp_listen.py', 'w') as f:
        f.write(udp_script)
    sftp.close()
    print(run(vm, "python3 /tmp/udp_listen.py", timeout=18))
    vm.close()

if __name__ == "__main__":
    main()
