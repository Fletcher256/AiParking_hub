#!/usr/bin/env python3
"""Clean warm start and UDP verification."""
import paramiko, time

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

def run(c, cmd, timeout=30):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace") + stderr.read().decode("utf-8", errors="replace")

def main():
    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)

    # Thorough kill
    print("=== Killing all related processes ===")
    run(board, "killall -9 sample_dtof 2>/dev/null; killall -9 'sleep' 2>/dev/null; sleep 3")
    ps = run(board, "ps | grep -E 'sample_dtof|sleep 7200' | grep -v grep || echo all_gone")
    print(ps.strip())

    # Start fresh
    print("\n=== Starting binary ===")
    run(board, "rm -f /tmp/dtof.log")
    board.exec_command(
        "cd /opt/sample/dtof && "
        "sleep 7200 | ./sample_dtof 3 192.168.137.100 > /tmp/dtof.log 2>&1 &"
    )

    # Wait and poll log every 5s for up to 40s
    print("Polling log for DtofInit success...")
    for i in range(8):
        time.sleep(5)
        log = run(board, "cat /tmp/dtof.log 2>/dev/null")
        i2c = log.count("I2C_WRITE error")
        dtof_ok = "DtofInit success" in log
        frame_err = "frame err" in log
        vb_fail = "vb_set_conf failed" in log
        ps_out = run(board, "ps | grep sample_dtof | grep -v grep | grep -v sh").strip()
        print(f"  t+{(i+1)*5}s | I2C={i2c} | DtofInit={dtof_ok} | FrameErr={frame_err} | VBfail={vb_fail} | {ps_out[:60]}")
        if dtof_ok or vb_fail:
            break

    # Show non-I2C log
    print("\n=== dtof.log (key messages) ===")
    log = run(board, "cat /tmp/dtof.log 2>/dev/null")
    for l in log.split("\n"):
        if "I2C_WRITE" not in l and l.strip():
            print(l)

    board.close()

    # UDP test on VM
    print("\n=== VM UDP listener port 2368 (10s) ===")
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
        if count <= 3:
            print(f'  PKT {count}: {len(data)} bytes from {addr[0]}:{addr[1]}')
    except: pass
s.close()
if count:
    print(f'SUCCESS: {count} packets, avg {sum(sizes)//len(sizes)} bytes')
else:
    print('NO DATA: 0 packets on port 2368')
"""
    sftp = vm.open_sftp()
    with sftp.open('/tmp/udp_listen.py', 'w') as f:
        f.write(udp_script)
    sftp.close()
    print(run(vm, "python3 /tmp/udp_listen.py", timeout=18))
    vm.close()

if __name__ == "__main__":
    main()
