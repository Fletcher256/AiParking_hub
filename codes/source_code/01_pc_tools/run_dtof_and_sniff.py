#!/usr/bin/env python3
"""
Run sample_dtof on board in foreground (with output),
simultaneously sniff UDP on VM.
"""
import paramiko, threading, time, re, sys

BOARD_HOST = "192.168.137.2"; BOARD_USER = "root"; BOARD_PASS = "ebaina"
VM_HOST    = "192.168.137.100"; VM_USER = "ebaina"; VM_PASS = "ebaina"
VM_IP      = "192.168.137.100"
LOGFILE    = "/tmp/dtof_sniff.log"

def ssh(h, u, p, t=30):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(h, username=u, password=p, timeout=t, banner_timeout=t, auth_timeout=t)
    return c

def run(c, cmd, t=20):
    _, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode("utf-8","replace")
    err = e.read().decode("utf-8","replace")
    return o.channel.recv_exit_status(), out, err

board_output = []

def stream_board(client, cmd):
    _, stdout, stderr = client.exec_command(cmd, timeout=15)
    for line in iter(stdout.readline, ""):
        board_output.append(line.rstrip())
        print(f"  [board] {line.rstrip()}")
    for line in iter(stderr.readline, ""):
        board_output.append("ERR:"+line.rstrip())
        print(f"  [board ERR] {line.rstrip()}")

vm   = ssh(VM_HOST, VM_USER, VM_PASS)
board = ssh(BOARD_HOST, BOARD_USER, BOARD_PASS)

# Start tcpdump on VM
run(vm, f"sudo pkill tcpdump 2>/dev/null; rm -f {LOGFILE}")
run(vm, f"echo '{VM_PASS}' | sudo -S tcpdump -i ens37 'udp and src host 192.168.137.2' -c 30 -n > {LOGFILE} 2>&1 &")
time.sleep(1.5)
print("[VM] tcpdump started")

# Run sample_dtof in thread (10s timeout)
cmd = f"cd /opt/sample/dtof && sh dtof_init.sh 2>&1; timeout 10 ./sample_dtof 1 {VM_IP} 2>&1"
print(f"[Board] {cmd}\n")
t = threading.Thread(target=stream_board, args=(board, cmd), daemon=True)
t.start()
t.join(timeout=14)

# Kill dtof and stop tcpdump
run(board, "pkill -f sample_dtof 2>/dev/null")
run(vm,    "sudo pkill tcpdump 2>/dev/null")
time.sleep(0.5)

_, log, _ = run(vm, f"cat {LOGFILE}")
print(f"\n[VM tcpdump]\n{log[:2000]}")

ports = re.findall(r"192\.168\.137\.2\.\d+\s*>\s*192\.168\.137\.100\.(\d+)", log)
if ports:
    p = max(set(ports), key=ports.count)
    print(f"\n>>> dToF UDP port = {p} <<<")
else:
    print("\n[!] No packets captured. Board output above shows the error.")

board.close(); vm.close()
