#!/bin/sh

ws73_ko_path=/opt/sample/ws73

show_help()
{
	printf "usage : $0 <index> \n";
	printf "index:\n";
	printf "    (0) Start SLE Client\n";
	printf "    (1) Stop  SLE Client\n";
	exit 0
}

sle_client_start()
{
	echo "sle_client_start"

	insmod $ws73_ko_path/plat_soc.ko
	insmod $ws73_ko_path/sle_soc.ko

	sleep 0.5;
	/opt/sample/ws73/sle_client_sample &
}

sle_client_stop()
{
	echo "sle_client_stop"

	killall sle_client_sample
	sleep 1;
	rmmod sle_soc
	rmmod plat_soc
}

case $1 in
	0)
		sle_client_start
		;;
	1)
		sle_client_stop
		;;
	-h|--help|"")
		show_help
		;;
esac