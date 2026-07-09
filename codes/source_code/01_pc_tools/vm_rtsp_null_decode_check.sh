#!/usr/bin/env bash
set -euo pipefail

URL="${1:-rtsp://192.168.137.2:554/live0}"
SECONDS_TO_RUN="${2:-20}"
LOG="${3:-/tmp/rtsp_null_decode_check.log}"
MODE="${4:-tcp_default}"

FFMPEG_ARGS=(-rtsp_transport tcp)
case "$MODE" in
  tcp_default)
    ;;
  tcp_genpts)
    FFMPEG_ARGS=(-fflags +genpts+igndts -rtsp_transport tcp)
    ;;
  tcp_lowdelay)
    FFMPEG_ARGS=(-rtsp_transport tcp -fflags nobuffer -flags low_delay)
    ;;
  *)
    echo "usage: $0 URL SECONDS LOG {tcp_default|tcp_genpts|tcp_lowdelay}" >&2
    exit 2
    ;;
esac

set +e
timeout "$((SECONDS_TO_RUN + 5))" ffmpeg \
  -hide_banner \
  -loglevel warning \
  "${FFMPEG_ARGS[@]}" \
  -i "$URL" \
  -an \
  -t "$SECONDS_TO_RUN" \
  -f null - 2>&1 | tee "$LOG"
rc="${PIPESTATUS[0]}"
set -e

echo "NULL_DECODE_RC=$rc"
echo "NULL_DECODE_LOG=$LOG"
echo -n "NULL_DECODE_ERROR_LINES="
grep -Eic 'error|corrupt|decode|non monotonically|no frame' "$LOG" || true
echo -n "NULL_DECODE_BAD_LINES="
grep -Eic 'error|corrupt|decode|no frame' "$LOG" || true
echo -n "NULL_DTS_WARNING_LINES="
grep -Eic 'non monotonically' "$LOG" || true
echo "NULL_DECODE_TAIL_BEGIN"
tail -30 "$LOG"
echo "NULL_DECODE_TAIL_END"
exit "$rc"
