#!/bin/sh
for HOST in serveo.net localhost.run; do
  for PORT in 22 443 2222 80 8080; do
    RESULT=$(curl -vs --connect-timeout 4 "telnet://$HOST:$PORT" 2>&1 | head -3)
    if echo "$RESULT" | grep -q "Connected\|SSH-\|220\|200"; then
      echo "OPEN: $HOST:$PORT"
    elif echo "$RESULT" | grep -q "refused"; then
      echo "REFUSED: $HOST:$PORT"
    else
      echo "BLOCKED: $HOST:$PORT"
    fi
  done
done
