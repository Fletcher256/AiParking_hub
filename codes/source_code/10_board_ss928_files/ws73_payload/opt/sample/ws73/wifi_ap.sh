#!/bin/sh

ws73_ko_path=/opt/sample/ws73

show_help()
{
	printf "usage : $0 <index> \n";
	printf "index:\n";
	printf "    (0) Start WiFi AP mode\n";
	printf "    (1) Stop  WiFi AP mode\n";
	exit 0
}

wifi_ap_start()
{
	echo "wifi_ap_start"

	insmod $ws73_ko_path/plat_soc.ko
	insmod $ws73_ko_path/wifi_soc.ko
	sleep 0.5;
	hostapd /etc/wireless/hostapd.conf &
	ifconfig wlan0 192.168.49.1
	udhcpd -S /etc/wireless/udhcpd.conf &
}

wifi_ap_stop()
{
	echo "wifi_ap_stop"

	killall hostapd
	killall udhcpd
	sleep 1;
	rmmod wifi_soc
	rmmod plat_soc
}

case $1 in
	0)
		wifi_ap_start
		;;
	1)
		wifi_ap_stop
		;;
	-h|--help|"")
		show_help
		;;
esac