#!/bin/sh
export LD_PRELOAD=/opt/parking/autopark/board_yolo_event_probe.so
exec /opt/sample/parking_yolo_seg_safe/sample_parking_yolo_rtsp_conf06_quiet_displayoff "$@"
