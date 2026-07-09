#!/bin/sh

ws73_ko_path=/opt/sample/ws73

show_help()
{
	printf "usage : $0 <index> \n";
	printf "index:\n";
	printf "    (0) Start BLE\n";
	printf "    (1) Stop  BLE\n";
	exit 0
}

ble_start()
{
	echo "ble_start"

	insmod $ws73_ko_path/plat_soc.ko
	insmod $ws73_ko_path/ble_soc.ko

	sleep 0.5
	dbus_result=`dbus-daemon --config-file=/usr/share/dbus-1/session.conf --print-address --fork`

	export DBUS_SESSION_BUS_ADDRESS=$dbus_result
	export DBUS_SYSTEM_BUS_ADDRESS=$dbus_result

	bluetoothd -n &

	sleep 0.5

	NORMAL="\033[0;39m"
	CYAN="\033[1;36m"
	GREEN="\033[1;32m"

	echo -e "${CYAN}将以下两行内容复制到终端并执行${NORMAL}"
	echo -e "${GREEN}export DBUS_SESSION_BUS_ADDRESS=$dbus_result${NORMAL}"
	echo -e "${GREEN}export DBUS_SYSTEM_BUS_ADDRESS=$dbus_result${NORMAL}"
}

ble_stop()
{
	echo "ble_stop"

	killall dbus-daemon
	killall bluetoothd
	rmmod ble_soc
	rmmod plat_soc
}


case $1 in
	0)
		ble_start
		;;
	1)
		ble_stop
		;;
	-h|--help|"")
		show_help
		;;
esac
