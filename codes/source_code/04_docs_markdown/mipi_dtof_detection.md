# MIPI dToF Detection Check

Date: 2026-05-26

## Goal

Check whether the board can currently detect the dToF module connected through the MIPI route.

## Commands And Findings

MIPI VI sample directory exists:

```text
/root/device_sample/mipi_vi/sample_vio
/root/device_sample/mipi_vi/scripts/init_imx347_4x2lan.sh
```

Before media stack initialization, `/dev` only exposed base I2C devices and no standard video/media nodes:

```text
/dev/i2c-0 ... /dev/i2c-5
no /dev/video*
no /dev/media*
```

After running the board media initialization script `/etc/init.d/S90AutoRun`, the SS928 media modules loaded successfully, including:

```text
ot_mipi_rx
ot_vi
ot_isp
ot_vpss
ot_sys
ot_base
```

The following device nodes appeared:

```text
/dev/ot_mipi_rx
/dev/vi
/dev/isp_dev
/dev/vpss
/dev/vb
/dev/sys
```

The media stack initialization log configured camera sensors, not dToF:

```text
sensor0: os08a20
sensor1: os08a20
sensor2: os08a20
sensor3: os08a20
```

`sample_vio` usage only lists supported camera modes:

```text
os08a20
imx347
imx485
```

No `tof`, `dtof`, or `depth` mode appears in the MIPI VI sample.

Standard Linux media/V4L2 detection did not find a device:

```text
v4l2-ctl --list-devices
Cannot open device /dev/video0, exiting.

media-ctl -p
Failed to enumerate /dev/media0 (-2)
```

Search results for dToF-related files only found temporary probe files and the unrelated CAN ToF sample:

```text
/root/device_sample/can/can_tof
```

## Conclusion

The board's MIPI media stack can be loaded, but the current software image does not detect or expose the connected MIPI dToF module as a known sensor.

Current evidence points to one of these cases:

1. The dToF module is not powered, not connected correctly, or its I2C control channel is not connected.
2. The module is connected, but the current image lacks the dToF sensor driver/configuration.
3. The MIPI sample in this image only supports camera sensors (`os08a20`, `imx347`, `imx485`) and cannot initialize this dToF module.
4. The dToF requires a vendor-specific initialization sequence, I2C address, lane configuration, and output format that are not present in the current sample.

## Next Required Information

To continue, collect the dToF module details:

- Exact dToF module model and vendor.
- MIPI lane count and lane mapping.
- I2C bus and address.
- Power rails and enable/reset pins.
- Initialization register sequence or vendor SDK/sample.
- Expected output format, such as RAW, depth map, confidence map, or custom packets.

Without those, the current board image does not provide enough software support to positively detect the dToF module over MIPI.
