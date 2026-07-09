#!/usr/bin/env python3
"""Upload file to board via SFTP (fallback: stdin pipe if SFTP unavailable)."""
import sys, paramiko
from pathlib import Path

BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def main():
    local_path  = sys.argv[1]
    remote_path = sys.argv[2]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=15)

    data = Path(local_path).read_bytes()
    print(f"Uploading {local_path} ({len(data)} bytes) -> {remote_path}")

    # Try SFTP first
    try:
        sftp = client.open_sftp()
        sftp.putfo(__import__("io").BytesIO(data), remote_path)
        sftp.close()
        print("SFTP upload OK")
        client.close()
        return
    except Exception as e:
        print(f"SFTP failed ({e}), falling back to chunked stdin pipe")

    # Fallback: base64-encode and write via echo
    import base64
    b64 = base64.b64encode(data).decode()
    # Write in chunks to avoid arg length limits
    chunk = 4096
    _, o, e = client.exec_command(f"rm -f {remote_path}", timeout=5)
    o.read(); e.read()

    # Use dd or python to decode - check what's available
    _, o, _ = client.exec_command("which base64", timeout=5)
    has_base64 = bool(o.read().strip())
    if not has_base64:
        print("No base64 on board, trying busybox base64")
        _, o, _ = client.exec_command("busybox base64 --help 2>&1 | head -1", timeout=5)
        print(o.read().decode())

    # Write b64 string to a temp file then decode
    tmp_b64 = "/tmp/_upload_b64.tmp"
    chan = client.get_transport().open_session()
    chan.exec_command(f"cat > {tmp_b64}")
    # Send in chunks
    for i in range(0, len(b64), 8192):
        chan.sendall(b64[i:i+8192].encode())
    chan.shutdown_write()
    chan.recv_exit_status()
    chan.close()

    # Decode
    _, o, e = client.exec_command(f"base64 -d {tmp_b64} > {remote_path} && rm {tmp_b64}", timeout=30)
    out = o.read().decode()
    err = e.read().decode()
    rc  = o.channel.recv_exit_status()
    if out: print(out)
    if err: print(err, file=sys.stderr)
    print(f"Decode rc={rc}")
    client.close()

if __name__ == "__main__":
    main()
