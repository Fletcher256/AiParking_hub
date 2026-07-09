#!/bin/sh

echo "DEV_TTY"
ls -l /dev | grep -E 'ttyUSB|ttyACM|ttyGS' || true

echo "USB_DEVICES"
for d in /sys/bus/usb/devices/*; do
    [ -f "$d/idVendor" ] || continue
    echo "===$d==="
    printf "idVendor="
    cat "$d/idVendor"
    printf "idProduct="
    cat "$d/idProduct"
    [ -f "$d/manufacturer" ] && { printf "manufacturer="; cat "$d/manufacturer"; }
    [ -f "$d/product" ] && { printf "product="; cat "$d/product"; }
    [ -f "$d/serial" ] && { printf "serial="; cat "$d/serial"; }
done

echo "USB_SERIAL_MODULES"
cat /proc/modules | grep -E 'ch34|ch341|ch343|cp210|ftdi|pl2303|cdc_acm|usbserial|option' || true

echo "DMESG_USB_SERIAL"
dmesg | grep -i -E 'ch34|ch341|ch343|cp210|ftdi|pl2303|cdc_acm|ttyUSB|ttyACM|usb serial|usbserial|1a86|7523' | tail -120 || true
