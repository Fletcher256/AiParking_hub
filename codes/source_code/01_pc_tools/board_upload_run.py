#!/usr/bin/env python3
"""Upload a file to board via SSH exec (no SFTP), then optionally run a command."""
import sys, paramiko, time

HOST = "192.168.137.2"
USER = "root"
PASS = "ebaina"

def upload(client, local_path, remote_path):
    with open(local_path, "rb") as f:
        data = f.read()
    chan = client.get_transport().open_session()
    chan.exec_command(f"cat > {remote_path} && chmod +x {remote_path}")
    chan.sendall(data)
    chan.shutdown_write()
    rc = chan.recv_exit_status()
    print(f"upload -> {remote_path}  rc={rc}")
    return rc

def run(client, cmd, timeout=60):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out: print(out, end="")
    if err: print(err, end="", file=sys.stderr)
    return rc

def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30, banner_timeout=30, auth_timeout=30)

    local  = sys.argv[1]
    remote = sys.argv[2]
    upload(client, local, remote)

    if len(sys.argv) > 3:
        cmd = sys.argv[3]
        print(f"\n--- running: {cmd} ---")
        rc = run(client, cmd, timeout=90)
        print(f"\n[exit={rc}]")

    client.close()

if __name__ == "__main__":
    main()
