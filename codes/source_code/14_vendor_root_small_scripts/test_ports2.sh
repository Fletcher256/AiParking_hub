#!/bin/sh
for PORT in 22 443 80 2222 8080; do
  OUT=$(curl -vs --connect-timeout 3 "telnet://serveo.net:$PORT" 2>&1)
  if echo "$OUT" | grep -q 'Connected\|SSH-\|220 '; then
    echo "OPEN $PORT"
  elif echo "$OUT" | grep -q refused; then
    echo "REFUSED $PORT"
  else
    echo "BLOCKED $PORT"
  fi
done
echo "done"
