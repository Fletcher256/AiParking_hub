#!/usr/bin/env python3
"""Copy one validated sample_dtof* binary from the VM to a safe dToF board directory."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
from pathlib import Path

import paramiko


VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"
DEFAULT_BOARD_DIR = "/opt/sample/official_dtof"
BOARD_UPLOAD_B64 = "/tmp/_codex_sample_dtof_upload.b64"
SAFE_BINARY_RE = re.compile(r"^sample_dtof[A-Za-z0-9_.-]*$")
SAFE_BOARD_DIR_RE = re.compile(r"^/opt/sample/(official_dtof|seller_dtof|seller_debug)$")


def connect(host: str, user: str, password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=30, banner_timeout=30, auth_timeout=30)
    return client


def validate_paths(vm_binary: str, board_dir: str, board_path: str) -> None:
    name = Path(vm_binary).name
    if not SAFE_BINARY_RE.fullmatch(name):
        raise ValueError(f"VM binary basename is not a safe sample_dtof* name: {name}")
    if not vm_binary.startswith("/home/ebaina/"):
        raise ValueError("VM binary must be under /home/ebaina/")
    if not SAFE_BOARD_DIR_RE.fullmatch(board_dir):
        raise ValueError(f"Board dir is not in the safe dToF set: {board_dir}")
    expected_prefix = f"{board_dir}/"
    if not board_path.startswith(expected_prefix):
        raise ValueError(f"Board path must be under {board_dir}")
    if Path(board_path).name != name:
        raise ValueError("Board destination basename must match VM binary basename")
    if not SAFE_BINARY_RE.fullmatch(Path(board_path).name):
        raise ValueError("Board destination basename is not safe")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-binary", required=True)
    parser.add_argument("--board-dir", default=DEFAULT_BOARD_DIR)
    parser.add_argument("--board-path", default="")
    args = parser.parse_args()

    binary_name = Path(args.vm_binary).name
    board_path = args.board_path or f"{args.board_dir}/{binary_name}"
    validate_paths(args.vm_binary, args.board_dir, board_path)

    vm = connect(VM_HOST, VM_USER, VM_PASS)
    try:
        sftp = vm.open_sftp()
        with sftp.file(args.vm_binary, "rb") as handle:
            data = handle.read()
        sftp.close()
    finally:
        vm.close()

    sha = hashlib.sha256(data).hexdigest()
    print(f"VM_BINARY={args.vm_binary}")
    print(f"BOARD_PATH={board_path}")
    print(f"BINARY_BYTES={len(data)}")
    print(f"BINARY_SHA256={sha}")

    board = connect(BOARD_HOST, BOARD_USER, BOARD_PASS)
    try:
        try:
            sftp = board.open_sftp()
            with sftp.file(board_path, "wb") as handle:
                handle.write(data)
            sftp.chmod(board_path, 0o755)
            sftp.close()
            print("BOARD_UPLOAD_METHOD=sftp")
        except Exception as exc:
            print(f"BOARD_UPLOAD_METHOD=ssh_base64_fallback reason={type(exc).__name__}: {exc}")
            b64 = base64.b64encode(data)
            channel = board.get_transport().open_session()
            channel.exec_command(f"cat > {BOARD_UPLOAD_B64}")
            for offset in range(0, len(b64), 8192):
                channel.sendall(b64[offset : offset + 8192])
            channel.shutdown_write()
            upload_rc = channel.recv_exit_status()
            channel.close()
            if upload_rc != 0:
                raise RuntimeError(f"board base64 upload failed rc={upload_rc}")
            decode_cmd = f"base64 -d {BOARD_UPLOAD_B64} > {board_path} && chmod 755 {board_path}"
            _, stdout, stderr = board.exec_command(decode_cmd, timeout=60)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            decode_rc = stdout.channel.recv_exit_status()
            if out:
                print(out, end="")
            if err:
                print(err, end="")
            if decode_rc != 0:
                raise RuntimeError(f"board base64 decode failed rc={decode_rc}")

        _, stdout, stderr = board.exec_command(f"sha256sum {board_path}; ls -l {board_path}", timeout=30)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if out:
            print(out, end="")
        if err:
            print(err, end="")
        print(f"BOARD_VERIFY_RC={rc}")
        return rc
    finally:
        board.close()


if __name__ == "__main__":
    raise SystemExit(main())
