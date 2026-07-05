#!/usr/bin/env bash
# Run on SSH login if Linux Ultra has not been configured yet.
if [ -f /var/lib/ultra/setup-complete ]; then
  return 0 2>/dev/null || exit 0
fi
if [ -f /etc/ultra/config.yaml ] && grep -q 'api_key:.' /etc/ultra/config.yaml 2>/dev/null; then
  return 0 2>/dev/null || exit 0
fi
echo ""
echo "Linux Ultra: first-boot setup is required."
echo "Run:  ultra setup --prod"
echo ""
return 0 2>/dev/null || true
