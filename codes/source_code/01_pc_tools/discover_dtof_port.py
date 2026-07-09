#!/usr/bin/env python3
"""
Discover the UDP port used by sample_dtof:
1. Start tcpdump on VM saving to file
2. Run sample_dtof on board for ~10 seconds
3. Read the tcpdump log to find destination port
"""
import paramiko, time, sys, re

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
VM_HOST    = "192.168.137.100"
VM_USER    = "ebaina"
VM_PASS    = "ebaina"

VM_IFACE  = "ens37"
BOARD_IP  = "192.168.137.2"
VM_IP     = "192.168.137.100"
DTOF_CASE = "1"
LOGFILE   = "/tmp/dtof_tcpdump.log"


def ssh(host, user, pw, timeout=30):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw,
              timeout=timeout, banner_timeout=timeout, auth_timeout=timeout)
    return c


def run(client, cmd, timeout=20):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    rc = out.channel.recv_exit_status()
    return rc, o, e


def main():
    print("=== dToF UDP Port Discovery ===\n")

    vm    = ssh(VM_HOST, VM_USER, VM_PASS)
    board = ssh(BOARD_HOST, BOARD_USER, BOARD_PASS)

    # Kill any lingering processes
    run(vm,    f"sudo pkill tcpdump 2>/dev/null; rm -f {LOGFILE}")
    run(board, "pkill -f sample_dtof 2>/dev/null")

    # ---- Step 1: Start tcpdump on VM (background, save to file) ----
    td_cmd = (
        f"echo '{VM_PASS}' | sudo -S tcpdump -i {VM_IFACE} "
        f"'udp and src host {BOARD_IP}' "
        f"-c 30 -n -q > {LOGFILE} 2>&1 &"
    )
    print(f"[VM] Starting tcpdump (bg) -> {LOGFILE}")
    vm.exec_command(f"bash -c {repr(td_cmd)}", timeout=5)
    time.sleep(1.5)

    # ---- Step 2: Run sample_dtof on board ----
    dtof_cmd = (
        f"cd /opt/sample/dtof && "
        f"sh dtof_init.sh 2>/dev/null; "
        f"./sample_dtof {DTOF_CASE} {VM_IP}"
    )
    print(f"[Board] Launching: ./sample_dtof {DTOF_CASE} {VM_IP}")
    board.exec_command(f"bash -c {repr(dtof_cmd)} &", timeout=5)

    # ---- Step 3: Wait for packets ----
    print("[*] Waiting 12s for dToF packets...")
    for i in range(12):
        time.sleep(1)
        rc, log, _ = run(vm, f"cat {LOGFILE} 2>/dev/null")
        if log and ">" in log:
            print(f"    {i+1}s: got data!")
            break
        print(f"    {i+1}s: waiting...", end="\r")

    # ---- Step 4: Kill sample_dtof ----
    run(board, "pkill -f sample_dtof 2>/dev/null")
    run(vm,    "sudo pkill tcpdump 2>/dev/null")
    time.sleep(0.5)

    # ---- Step 5: Read and parse log ----
    rc, log, _ = run(vm, f"cat {LOGFILE}")
    print(f"\n[VM] tcpdump log:\n{log[:3000]}")

    # Parse: "IP 192.168.137.2.SPORT > 192.168.137.100.DPORT: UDP, length N"
    ports = re.findall(
        rf"192\.168\.137\.2\.(\d+)\s*>\s*192\.168\.137\.100\.(\d+)",
        log
    )
    if ports:
        dst_ports = [int(p[1]) for p in ports]
        most_common = max(set(dst_ports), key=dst_ports.count)
        print(f"\n>>> Detected UDP destination port: {most_common} <<<")
        print(f"    (seen in {len(ports)} packets, all dst ports: {sorted(set(dst_ports))})")
        return most_common
    else:
        # Also check board output
        rc2, bout, _ = run(board, "dmesg 2>/dev/null | tail -5")
        print(f"\n[Board] dmesg tail: {bout[:300]}")
        print("\n[!] No UDP packets captured.")
        print("    Possible reasons:")
        print("    1. sample_dtof failed to start (dToF hardware issue?)")
        print("    2. Firewall blocking UDP on VM")
        print("    3. sample_dtof sends to a different port range")
        return None

    board.close()
    vm.close()


if __name__ == "__main__":
    main()
