#!/bin/sh
# Check ZeroTier download options
echo "=== install.zerotier.com ==="
curl -sk --max-time 10 'https://install.zerotier.com' 2>/dev/null | head -30
echo ""
echo "=== GitHub latest release tag ==="
curl -sk --max-time 10 'https://api.github.com/repos/zerotier/ZeroTierOne/releases/latest' 2>/dev/null | grep '"tag_name"'
