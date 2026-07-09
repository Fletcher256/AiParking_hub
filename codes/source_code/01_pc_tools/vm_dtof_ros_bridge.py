#!/usr/bin/env python3
"""Standalone dToF-only ROS2 bridge (run directly on the VM, no colcon).

Listens for the SS-LD-AS01 / GS1860 4873-byte UDP packets and publishes:
  /dtof/points  sensor_msgs/PointCloud2  (xyz in metres + depth_mm)
  /dtof/depth   sensor_msgs/Image (32FC1, mm; invalid -> NaN)
  /dtof/info    sensor_msgs/CameraInfo

Differences vs parking_bridge/dtof_bridge.py:
  - Uses sane FOV-derived intrinsics (the EEPROM calib in the packet is degenerate:
    fy=1, cx=0, cy=0), so the point cloud is geometrically meaningful.
  - Filters the 2 mm "no valid peak" sentinel and out-of-range depths to NaN.
  - Vectorized with numpy.

Run:
  source /opt/ros/humble/setup.bash
  python3 /tmp/vm_dtof_ros_bridge.py
"""
import socket
import struct
import threading

import numpy as np
import rclpy
from rclpy.node import Node
from builtin_interfaces.msg import Time
from sensor_msgs.msg import Image, PointCloud2, PointField, CameraInfo
from std_msgs.msg import Header

try:
    import cv2
    _HAVE_CV2 = True
except Exception:
    _HAVE_CV2 = False

PIXELS_H = 30
PIXELS_W = 40
PIXELS_TOTAL = PIXELS_H * PIXELS_W  # 1200

HEAD_FMT = '<hh Ih II hhh B 12f'
HEAD_SIZE = struct.calcsize(HEAD_FMT)   # 73
PIXEL_SIZE = 4
PACKET_SIZE = HEAD_SIZE + PIXELS_TOTAL * PIXEL_SIZE  # 4873

# FOV-derived intrinsics: GS1860 is ~60 deg (H) x 46 deg (V), 40x30.
import math
HFOV_DEG = 60.0
VFOV_DEG = 46.0
FX = (PIXELS_W / 2.0) / math.tan(math.radians(HFOV_DEG / 2.0))   # ~34.6
FY = (PIXELS_H / 2.0) / math.tan(math.radians(VFOV_DEG / 2.0))   # ~35.3
CX = (PIXELS_W - 1) / 2.0   # 19.5
CY = (PIXELS_H - 1) / 2.0   # 14.5

SENTINEL_MM = 2     # DtofProcess "no valid peak" output
MIN_VALID_MM = 3    # treat <=2mm as invalid
MAX_VALID_MM = 9000

PC2_FIELDS = [
    PointField(name='x',        offset=0,  datatype=PointField.FLOAT32, count=1),
    PointField(name='y',        offset=4,  datatype=PointField.FLOAT32, count=1),
    PointField(name='z',        offset=8,  datatype=PointField.FLOAT32, count=1),
    PointField(name='depth_mm', offset=12, datatype=PointField.FLOAT32, count=1),
]
PC2_POINT_STEP = 16

# Precompute pixel grid (optical frame: x right, y down, z forward)
_u = np.tile(np.arange(PIXELS_W, dtype=np.float32), PIXELS_H)
_v = np.repeat(np.arange(PIXELS_H, dtype=np.float32), PIXELS_W)


class DtofBridge(Node):
    def __init__(self):
        super().__init__('dtof_bridge')
        self.declare_parameter('udp_port', 2368)
        self.declare_parameter('frame_id', 'dtof')
        self._port = self.get_parameter('udp_port').value
        self._frame_id = self.get_parameter('frame_id').value

        self._pub_pc2 = self.create_publisher(PointCloud2, '/dtof/points', 10)
        self._pub_depth = self.create_publisher(Image, '/dtof/depth', 10)
        self._pub_color = self.create_publisher(Image, '/dtof/depth_color', 10)
        self._pub_info = self.create_publisher(CameraInfo, '/dtof/info', 10)
        self._color_max_mm = 5000.0
        self._color_scale = 12  # upscale 40x30 -> 480x360 for visibility

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('0.0.0.0', self._port))
        self._sock.settimeout(1.0)

        self._count = 0
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        self.get_logger().info(
            f'dtof bridge on UDP {self._port}; intrinsics fx={FX:.2f} fy={FY:.2f} '
            f'cx={CX:.1f} cy={CY:.1f}')

    def destroy_node(self):
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
        super().destroy_node()

    def _recv_loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < PACKET_SIZE:
                continue
            try:
                self._process(data)
            except Exception as e:  # noqa
                self.get_logger().error(f'parse error: {e}')

    def _now_header(self):
        t = self.get_clock().now().to_msg()
        return Header(stamp=t, frame_id=self._frame_id)

    def _publish_color(self, hdr, raw, valid):
        # Normalize valid depths 0..color_max_mm -> 0..255, colormap, invalid black.
        norm = np.clip(raw / self._color_max_mm, 0.0, 1.0)
        g8 = (norm * 255.0).astype(np.uint8).reshape(PIXELS_H, PIXELS_W)
        if _HAVE_CV2:
            color = cv2.applyColorMap(g8, cv2.COLORMAP_JET)  # BGR
            color = color[:, :, ::-1].copy()                 # -> RGB
        else:
            color = np.dstack([g8, np.zeros_like(g8), 255 - g8])
        invalid = ~valid.reshape(PIXELS_H, PIXELS_W)
        color[invalid] = 0
        s = self._color_scale
        big = np.repeat(np.repeat(color, s, axis=0), s, axis=1)
        msg = Image()
        msg.header = hdr
        msg.height = big.shape[0]
        msg.width = big.shape[1]
        msg.encoding = 'rgb8'
        msg.step = big.shape[1] * 3
        msg.data = big.astype(np.uint8).tobytes()
        self._pub_color.publish(msg)

    def _process(self, data: bytes):
        # depth = first int16 of each 4-byte pixel
        raw = np.frombuffer(data, dtype='<i2', count=PIXELS_TOTAL * 2,
                            offset=HEAD_SIZE)[0::2].astype(np.float32)
        valid = (raw >= MIN_VALID_MM) & (raw <= MAX_VALID_MM)
        z_mm = np.where(valid, raw, np.nan)

        hdr = self._now_header()

        # CameraInfo
        info = CameraInfo()
        info.header = hdr
        info.width = PIXELS_W
        info.height = PIXELS_H
        info.k = [FX, 0.0, CX, 0.0, FY, CY, 0.0, 0.0, 1.0]
        info.distortion_model = 'plumb_bob'
        self._pub_info.publish(info)

        # Depth image (mm, invalid -> NaN), raw 32FC1 for tools.
        img = Image()
        img.header = hdr
        img.width = PIXELS_W
        img.height = PIXELS_H
        img.encoding = '32FC1'
        img.step = PIXELS_W * 4
        img.data = z_mm.astype(np.float32).tobytes()
        self._pub_depth.publish(img)

        # Colorized depth image (rgb8) — easy to view in a Foxglove Image panel.
        self._publish_color(hdr, raw, valid)

        # PointCloud2. ROS body convention (x forward, y left, z up) so it sits
        # naturally in front of the camera in Foxglove's z-up 3D view.
        z_m = z_mm / 1000.0
        x_opt = (_u - CX) * z_m / FX   # right
        y_opt = (_v - CY) * z_m / FY   # down
        pts = np.empty((PIXELS_TOTAL, 4), dtype=np.float32)
        pts[:, 0] = z_m            # forward
        pts[:, 1] = -x_opt         # left
        pts[:, 2] = -y_opt         # up
        pts[:, 3] = z_mm
        pc = PointCloud2()
        pc.header = hdr
        pc.height = 1
        pc.width = PIXELS_TOTAL
        pc.fields = PC2_FIELDS
        pc.is_bigendian = False
        pc.point_step = PC2_POINT_STEP
        pc.row_step = PC2_POINT_STEP * PIXELS_TOTAL
        pc.is_dense = False
        pc.data = pts.tobytes()
        self._pub_pc2.publish(pc)

        self._count += 1
        if self._count % 50 == 1:
            n_valid = int(valid.sum())
            self.get_logger().info(
                f'pkt#{self._count} valid_px={n_valid} '
                f'z_mm[min..max]={"nan" if n_valid==0 else int(np.nanmin(z_mm))}..'
                f'{"nan" if n_valid==0 else int(np.nanmax(z_mm))}')


def main():
    rclpy.init()
    node = DtofBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
