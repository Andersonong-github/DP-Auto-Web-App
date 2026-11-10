#!/usr/bin/env bash
# Pre-deployment environment recon: run on the Proxmox node, read-only, changes nothing.
echo "===== Node ====="
hostname
pveversion | head -1
uname -m
echo
echo "===== Resources ====="
free -m | head -2
df -h /var/lib/vz | tail -1
echo
echo "===== Storage ====="
pvesm status
echo
echo "===== Existing containers / VMs ====="
pct list
qm list
echo
echo "===== Available templates ====="
pveam list local 2>/dev/null | head
echo
echo "===== Network ====="
ip -br a | grep -v ' lo ' | head -4
ip r | head -4
echo
echo "===== Free IP scan (10.10.7.201-245) ====="
for i in $(seq 201 245); do
  ( ping -c1 -W1 "10.10.7.$i" >/dev/null 2>&1 && echo "10.10.7.$i ALIVE" ) &
done
wait
echo "Scan complete: anything not listed above is currently unanswered"
echo
echo "===== Tools and outbound network ====="
command -v skopeo || echo "no skopeo"
command -v docker || echo "no docker(node)"
command -v buildah || echo "no buildah"
timeout 8 curl -s -o /dev/null -w 'docker-hub=%{http_code}\n' https://registry-1.docker.io/v2/ || echo "outbound network failed"
timeout 8 curl -s -o /dev/null -w 'deb-debian=%{http_code}\n' http://deb.debian.org/debian/ || echo "apt source unreachable"
echo
echo "===== Does the casaos container have docker ====="
pct exec 103 -- docker --version 2>&1 | head -2 || true
echo
echo "===== Reference: cloudflared container network config ====="
pct config 100 | grep -E 'net0|rootfs|memory|unprivileged' || true
