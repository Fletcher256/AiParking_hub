#!/usr/bin/env python3
"""Validate the board camera RTSP stream from the Ubuntu VM."""

from __future__ import annotations

import argparse
import textwrap


DEFAULT_HOST = "192.168.137.100"
DEFAULT_USER = "ebaina"
DEFAULT_PASSWORD = "ebaina"
DEFAULT_URL = "rtsp://192.168.137.2:554/live0"


def build_remote_script(url: str, seconds: int, attempt_timeout: int, min_stream_seconds: int) -> str:
    return f"""
import subprocess
import time

URL = {url!r}
SECONDS = {seconds}
ATTEMPT_TIMEOUT = {attempt_timeout}
MIN_STREAM_SECONDS = {min_stream_seconds}

deadline = time.monotonic() + SECONDS
attempt = 0
last_rc = None
last_elapsed = 0.0
last_output = ""

while time.monotonic() < deadline:
    attempt += 1
    started = time.monotonic()
    cmd = [
        "timeout", str(ATTEMPT_TIMEOUT),
        "gst-launch-1.0", "-q",
        "rtspsrc", "location=" + URL, "latency=100", "protocols=tcp",
        "!", "rtph265depay",
        "!", "fakesink", "sync=false",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    elapsed = time.monotonic() - started
    last_rc = proc.returncode
    last_elapsed = elapsed
    last_output = proc.stdout[-2000:]
    if proc.returncode in (0, 124) and elapsed >= MIN_STREAM_SECONDS:
        print(f"RTSP_URL={{URL}}")
        print(f"RTSP_ATTEMPTS={{attempt}}")
        print(f"RTSP_LAST_RC={{proc.returncode}}")
        print(f"RTSP_LAST_ELAPSED={{elapsed:.2f}}")
        print("RTSP_CHECK=PASS")
        raise SystemExit(0)
    time.sleep(1)

print(f"RTSP_URL={{URL}}")
print(f"RTSP_ATTEMPTS={{attempt}}")
print(f"RTSP_LAST_RC={{last_rc}}")
print(f"RTSP_LAST_ELAPSED={{last_elapsed:.2f}}")
if last_output:
    print("RTSP_LAST_OUTPUT_BEGIN")
    print(last_output, end="" if last_output.endswith("\\n") else "\\n")
    print("RTSP_LAST_OUTPUT_END")
print("RTSP_CHECK=FAIL")
raise SystemExit(1)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--attempt-timeout", type=int, default=8)
    parser.add_argument("--min-stream-seconds", type=int, default=5)
    args = parser.parse_args()

    try:
        import paramiko
    except ImportError:
        print("paramiko is not installed. Use .venv\\Scripts\\python in this workspace.")
        return 2

    remote_script = textwrap.dedent(
        build_remote_script(args.url, args.seconds, args.attempt_timeout, args.min_stream_seconds)
    )
    command = "python3 - <<'PY'\n" + remote_script + "\nPY"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=args.seconds + 20)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
    finally:
        client.close()

    if out:
        print(out, end="")
    if err:
        print(err, end="")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
