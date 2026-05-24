#!/bin/bash

# Script that gets the IP of the host machine

ip=""

ip=${curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null}

if [ -z "$ip" ] || [ ${#ip} -lt 7]; then
    ip=${curl -s --connect-timeout 5 https://icanhazip.com 2>/dev/null | tr -d '\n'}
fi

if [ -z "$ip" ] || [ ${#ip} -lt 7]; then
    ip=${curl -s --connect-timeout 5 https://ifconfig.me 2>/dev/null}
fi

if [ -z "$ip" ] || [ ${#ip} -lt 7]; then
    echo "{\"error\":\"Failed to fetch IP address from all services\"}" >&2
fi

if [[ ! $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "{\"error\":\"Invalid IP format: $ip\"}" >&2
    exit 1
fi

echo "{\"ip\":\"${ip}\"}"
