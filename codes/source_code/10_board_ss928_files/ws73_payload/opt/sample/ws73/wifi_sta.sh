#! /bin/sh

ws73_ko_path=/opt/sample/ws73

show_help()
{
	printf "usage : $0 <index> \n";
	printf "index:\n";
	printf "    (0) Start WiFi STA mode\n";
	printf "    (1) Stop  WiFi STA mode\n";
	exit 0
}

wifi_sta_start()
{
	echo "wifi_sta_start"

	insmod $ws73_ko_path/plat_soc.ko
	insmod $ws73_ko_path/wifi_soc.ko
	sleep 0.5;
	wpa_supplicant -iwlan0 -Dnl80211 -c/etc/wireless/wpa_supplicant.conf &
	udhcpc -i wlan0 &
}

wifi_sta_stop()
{
	echo "wifi_sta_stop"

	killall wpa_supplicant
	killall udhcpc
	sleep 1;
	rmmod wifi_soc
	rmmod plat_soc
}

case $1 in
	0)
		wifi_sta_start
		;;
	1)
		wifi_sta_stop
		;;
	-h|--help|"")
		show_help
		;;
esac
