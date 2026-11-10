#!/usr/bin/env bash
# Check whether candidate static IPs are already in use (ARP probe + ping), read-only.
CANDIDATES="${*:-10.10.7.230 10.10.7.231 10.10.7.232}"

echo "arping availability: $(command -v arping || echo 'not installed')"
echo
for ip in $CANDIDATES; do
  mac=""
  if command -v arping >/dev/null 2>&1; then
    if arping -D -I vmbr0 -c 3 -w 3 "$ip" >/dev/null 2>&1; then
      echo "$ip  free (arping got no reply)"
      continue
    else
      echo "$ip  in use (arping got a reply)"
      continue
    fi
  fi
  if ping -c1 -W1 "$ip" >/dev/null 2>&1; then
    echo "$ip  in use (ping got a reply)"
    continue
  fi
  mac=$(ip neigh show "$ip" | awk '{print $5}' | head -1)
  if [ -n "$mac" ]; then
    echo "$ip  present in ARP table ($mac), possibly in use"
  else
    echo "$ip  no conflict found (based on ping + ARP table only, not fully reliable)"
  fi
done
