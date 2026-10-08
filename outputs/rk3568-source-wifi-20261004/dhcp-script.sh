#!/bin/sh
# BusyBox udhcpc hook. Configure only the requested wlan0 RAM runtime.
set -eu
test "$interface" = wlan0
case "$1" in
    deconfig)
        ip addr flush dev wlan0
        ;;
    bound|renew)
        test -n "$ip"
        ip addr flush dev wlan0
        # udhcpc exports a dotted subnet; BusyBox ip accepts dotted netmasks.
        ip addr add "$ip/${subnet:-255.255.255.0}" dev wlan0
        if [ -n "${router:-}" ]; then
            set -- $router
            ip route replace default via "$1" dev wlan0
        fi
        : > /etc/resolv.conf
        for server in ${dns:-}; do
            printf 'nameserver %s\n' "$server" >> /etc/resolv.conf
        done
        echo DHCP_IPV4_CONFIGURED
        ;;
esac
