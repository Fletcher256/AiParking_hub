#!/bin/sh
curl -sk 'https://download.zerotier.com/redhat/el/8/aarch64/' 2>/dev/null | grep -o 'zerotier[^"]*rpm' | head -10
