#!/usr/bin/env python3
"""
Camera H265 TCP server for SS928 board.

Workflow:
  1. Create FIFO at stream_chn0.h265 (replaces regular file)
  2. Start sample_vio 0 1 (writes H265 Annex B to FIFO)
  3. Open FIFO for reading (unblocks once sample_vio opens for write)
  4. Accept TCP client; stream FIFO bytes to client
  5. Drain FIFO continuously so sample_vio never blocks, even when no client is connected

Run from /opt/sample/mipi_rx/os08a20/:
  python3 camera_tcp_server.py [--port 5000]
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time

WORK_DIR  = '/opt/sample/mipi_rx/os08a20'
FIFO_NAME = 'stream_chn0.h265'
TCP_PORT  = 5000
CHUNK     = 65536
FIFO_OPEN_TIMEOUT = 20  # seconds to wait for sample_vio to open FIFO

_vio_proc = None
_running  = True


def _cleanup():
    global _running
    _running = False
    if _vio_proc and _vio_proc.poll() is None:
        _vio_proc.terminate()
        try:
            _vio_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _vio_proc.kill()
    fifo = os.path.join(WORK_DIR, FIFO_NAME)
    if os.path.exists(fifo):
        try:
            os.remove(fifo)
        except OSError:
            pass


def _sig_handler(signum, frame):
    print('\n[camera] signal received, shutting down', flush=True)
    _cleanup()
    sys.exit(0)


def main():
    global _vio_proc

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=TCP_PORT)
    args = parser.parse_args()
    port = args.port

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    os.chdir(WORK_DIR)
    fifo_path = os.path.join(WORK_DIR, FIFO_NAME)

    # Create FIFO (replaces any existing file or stale FIFO)
    if os.path.exists(fifo_path):
        os.remove(fifo_path)
    os.mkfifo(fifo_path)
    print(f'[camera] FIFO created: {fifo_path}', flush=True)

    # TCP server
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.listen(1)
    srv.settimeout(2.0)
    print(f'[camera] TCP server listening on :{port}', flush=True)

    # Start sample_vio (it will try to open FIFO for writing)
    _vio_proc = subprocess.Popen(
        ['./sample_vio', '0', '1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(f'[camera] sample_vio started (pid={_vio_proc.pid})', flush=True)

    # Open FIFO for reading in a thread — blocks until sample_vio opens for write
    fifo_file = [None]
    fifo_ready = threading.Event()

    def _open_fifo():
        fifo_file[0] = open(fifo_path, 'rb')
        fifo_ready.set()
        print('[camera] FIFO open for reading', flush=True)

    threading.Thread(target=_open_fifo, daemon=True).start()

    if not fifo_ready.wait(timeout=FIFO_OPEN_TIMEOUT):
        print(f'[camera] ERROR: FIFO not opened within {FIFO_OPEN_TIMEOUT}s', flush=True)
        _cleanup()
        sys.exit(1)

    fifo = fifo_file[0]

    # Current TCP client connection (only one at a time)
    current_conn = [None]
    conn_lock = threading.Lock()

    def _drain_loop():
        """Read FIFO continuously; forward to TCP client when connected."""
        while _running:
            try:
                chunk = fifo.read(CHUNK)
            except OSError:
                break
            if not chunk:
                break  # sample_vio exited

            with conn_lock:
                c = current_conn[0]
            if c is None:
                continue  # no client — chunk is discarded (drains FIFO so vio doesn't block)

            try:
                c.sendall(chunk)
            except OSError:
                with conn_lock:
                    current_conn[0] = None
                print('[camera] client disconnected (send error)', flush=True)

    threading.Thread(target=_drain_loop, daemon=True).start()
    print('[camera] drain loop started, waiting for client', flush=True)

    while _running:
        # Check if sample_vio is still alive
        if _vio_proc.poll() is not None:
            print('[camera] sample_vio exited — stopping server', flush=True)
            break

        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        print(f'[camera] client {addr} connected', flush=True)
        with conn_lock:
            old = current_conn[0]
            if old:
                try:
                    old.close()
                except OSError:
                    pass
            current_conn[0] = conn

    srv.close()
    _cleanup()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        _cleanup()
