#!/bin/sh

ws73_ko_path=/opt/sample/ws73

show_help()
{
	printf "usage : $0 <index> \n";
	printf "index:\n";
	printf "    (0) Start SLE Server\n";
	printf "    (1) Stop  SLE Server\n";
	exit 0
}

sle_server_start()
{
	echo "sle_server_start"

	insmod $ws73_ko_path/plat_soc.ko
	insmod $ws73_ko_path/sle_soc.ko

	sleep 0.5;
	/opt/sample/ws73/sle_server_sample &
}

sle_server_stop()
{
	echo "sle_server_stop"

	killall sle_server_sample
	sleep 1;
	rmmod sle_soc
	rmmod plat_soc
}

case $1 in
	0)
		sle_server_start
		;;
	1)
		sle_server_stop
		;;
	-h|--help|"")
		show_help
		;;
esac