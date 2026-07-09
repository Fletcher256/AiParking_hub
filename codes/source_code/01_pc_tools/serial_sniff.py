#!/usr/bin/env python3
"""Just read from serial port for N seconds and print whatever comes."""
import serial, time, sys

PORT = "COM11"
BAUD = 115200
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

ser = serial.Serial(port=PORT, baudrate=BAUD, timeout=0.2)
end = time.monotonic() + DURATION
buf = b""
print(f"Reading {PORT} for {DURATION}s...")
while time.monotonic() < end:
    waiting = ser.in_waiting
    if waiting:
        chunk = ser.read(waiting)
        buf += chunk
        try:
            print(chunk.decode("utf-8", errors="replace"), end="", flush=True)
        except Exception:
            pass
    else:
        time.sleep(0.05)
ser.close()
print(f"\n[total bytes: {len(buf)}]")
