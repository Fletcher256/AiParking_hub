#!/bin/sh
set -eu

ssid="${1:-}"
psk="${2:-}"

if [ -z "$ssid" ] || [ -z "$psk" ]; then
  echo "usage: $0 <ssid> <psk>" >&2
  exit 2
fi

iface="${IFACE:-wlan0}"
wpa_cli_bin="${WPA_CLI_BIN:-/usr/local/bin/wpa_cli}"

echo "SWITCH_WIFI_BEGIN"
echo "IFACE=$iface"
echo "TARGET_SSID=$ssid"

if ! "$wpa_cli_bin" -i "$iface" status >/dev/null 2>&1; then
  echo "ERROR=wpa_cli_status_failed"
  exit 1
fi

"$wpa_cli_bin" -i "$iface" disconnect >/dev/null 2>&1 || true
"$wpa_cli_bin" -i "$iface" remove_network all >/dev/null 2>&1 || true

netid="$("$wpa_cli_bin" -i "$iface" add_network | tail -n 1)"
case "$netid" in
  ''|FAIL|UNKNOWN*)
    echo "ERROR=add_network_failed"
    exit 1
    ;;
esac

"$wpa_cli_bin" -i "$iface" set_network "$netid" ssid "\"$ssid\""
"$wpa_cli_bin" -i "$iface" set_network "$netid" psk "\"$psk\""
"$wpa_cli_bin" -i "$iface" set_network "$netid" key_mgmt WPA-PSK
"$wpa_cli_bin" -i "$iface" set_network "$netid" scan_ssid 1
"$wpa_cli_bin" -i "$iface" enable_network "$netid"
"$wpa_cli_bin" -i "$iface" save_config
"$wpa_cli_bin" -i "$iface" reconnect

for i in 1 2 3 4 5 6 7 8 9 10; do
  state="$("$wpa_cli_bin" -i "$iface" status 2>/dev/null | sed -n 's/^wpa_state=//p')"
  cur_ssid="$("$wpa_cli_bin" -i "$iface" status 2>/dev/null | sed -n 's/^ssid=//p')"
  echo "WAIT_$i state=$state ssid=$cur_ssid"
  [ "$state" = "COMPLETED" ] && [ "$cur_ssid" = "$ssid" ] && break
  sleep 2
done

echo "WPA_STATUS"
"$wpa_cli_bin" -i "$iface" status 2>/dev/null | sed -n '/^bssid=/p;/^freq=/p;/^ssid=/p;/^id=/p;/^mode=/p;/^pairwise_cipher=/p;/^group_cipher=/p;/^key_mgmt=/p;/^wpa_state=/p;/^address=/p;/^ip_address=/p'

echo "DHCP_RENEW"
udhcpc -i "$iface" -n -q -t 5 -T 3 2>&1 || true
sleep 2

echo "FINAL_STATUS"
"$wpa_cli_bin" -i "$iface" status 2>/dev/null | sed -n '/^bssid=/p;/^freq=/p;/^ssid=/p;/^id=/p;/^mode=/p;/^pairwise_cipher=/p;/^group_cipher=/p;/^key_mgmt=/p;/^wpa_state=/p;/^address=/p;/^ip_address=/p'

echo "FIB_ADDRS"
cat /proc/net/fib_trie 2>/dev/null | sed -n '/10\./p;/172\./p;/192\.168\./p' || true

echo "PING_PUBLIC"
ping -c 1 -W 3 223.5.5.5 2>/dev/null || true
echo "SWITCH_WIFI_END"
