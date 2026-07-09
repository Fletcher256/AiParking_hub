#!/usr/bin/env python3
"""Send enter key and read response from board serial."""
import serial, time

PORT = "COM11"
BAUD = 115200

ser = serial.Serial(port=PORT, baudrate=BAUD, timeout=0.5)
print(f"Opened {PORT}")

# Send multiple newlines to wake the shell
for _ in range(3):
    ser.write(b"\r\n")
    time.sleep(0.3)

# Read for 5 seconds
end = time.monotonic() + 5.0
buf = b""
while time.monotonic() < end:
    waiting = ser.in_waiting
    if waiting:
        chunk = ser.read(waiting)
        buf += chunk
        print(chunk.decode("utf-8", errors="replace"), end="", flush=True)
    else:
        time.sleep(0.05)

ser.close()
print(f"\n[total: {len(buf)} bytes]")
