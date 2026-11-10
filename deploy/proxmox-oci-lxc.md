# Deploy to Proxmox VE (OCI Application Container / OCI-as-LXC)

**This document was verified in a real environment** (not a flow copied from the docs):

| Item | Measured value |
|---|---|
| Node | `Proxmoxmbic` / Proxmox VE **9.2.21** / Debian 13 / x86_64 |
| Container | CT **113** `dp-auto-web`, unprivileged, 512MB / 1 core / 4GB disk (`sda_storage`) |
| Address | **http://192.0.2.230:8080** (host-managed network, vmbr0, dedicated IP, no port mapping needed) |
| Key output | `Detected OCI archive` + `Auto-Enabling host-managed network for network device net0.` |
| Verification | Recovers 4 seconds after reboot; real PBX login succeeded; all 4 read-only probes returned HTTP 200 |

One-shot script: [`pve-deploy-oci.sh`](pve-deploy-oci.sh) (build → convert to OCI archive → create container → inject env vars → verify).

---

## 0. Prerequisites

| PVE version | Option |
|---|---|
| **9.1 and above** | Native OCI (the main flow in this document) |
| 8.4 / 9.0 | See [section 8](#8-alternatives-for-pve--91) |

The node needs: `skopeo` (`apt-get install -y skopeo`), outbound network access, and a directory storage that supports `vztmpl`.

---

## 1. Package the source (on the dev machine)

```powershell
# only package what is needed at runtime
tar -czf dp-auto-web-src.tar.gz -C <project dir> backend frontend Dockerfile requirements.txt
```

Upload to the node: `scp dp-auto-web-src.tar.gz root@192.0.2.10:/root/`
(The repo includes `scripts/pve_ssh.py`, or you can use `--put` to upload over SSH.)

---

## 2. Build the image

No docker on the node is fine -- the script **borrows any container that has docker installed** to build
(in testing it borrowed CT 103 `casaos`, Docker 29.8.1):

```bash
SRC_TAR=/root/dp-auto-web-src.tar.gz BUILD_CT=103 ./pve-deploy-oci.sh
```

What the script does internally (every step was tested):

1. Unpack the source on the node → pack it into a build-context tar;
2. `pct push` into the build container → `docker build` (the first run pulls `python:3.12-slim`, about 9 seconds);
3. `docker save` → `pct pull` back to the node (about 169MB);
4. `skopeo copy docker-archive:… oci-archive:…` writes it into `<template storage>/template/cache/`;
5. Clean up the temporary files and images in the build container.

> If the node has docker installed itself, use `BUILD_ON=node` to build on the node directly.

---

## 3. Create the container

```bash
VMID=113 IP_CIDR=192.0.2.230/24 GATEWAY=192.0.2.1 STORAGE=sda_storage ./pve-deploy-oci.sh
```

**Expected output** (the two key lines):

```
Detected OCI archive
Auto-Enabling host-managed network for network device net0.
Detected container architecture: amd64
```

After creation, `/etc/pve/lxc/113.conf` looks like this (PVE translates the image metadata for you):

```
arch: amd64
cores: 1
entrypoint: python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8080 --workers 1 --proxy-headers
hostname: dp-auto-web
memory: 512
net0: name=eth0,bridge=vmbr0,gw=192.0.2.1,host-managed=1,hwaddr=...,ip=192.0.2.230/24,type=veth
onboot: 1
ostype: debian
rootfs: sda_storage:113/vm-113-disk-0.raw,size=4G
unprivileged: 1
lxc.init.uid: 10001          # the non-root user from the image is inherited
lxc.signal.halt: SIGTERM
lxc.environment.runtime: DP_...
```

---

## 4. Environment variables

The image already ships safe defaults. To override them, append
`lxc.environment.runtime:` lines to `/etc/pve/lxc/<vmid>.conf`, then run `pct reboot <vmid>` (**for the same name, the later occurrence wins**;
the script uses `sed` to delete the old line first, then appends):

| Variable | Value in this environment | Notes |
|---|---|---|
| `DP_TRUST_PROXY_HEADERS` | `1` | Turn on behind Cloudflare Tunnel / a reverse proxy; login throttling then counts by the real client IP |
| `DP_COOKIE_SECURE` | `0` | Set to `1` only when access is all HTTPS (**with `1`, a direct HTTP connection cannot log in**, because a Secure cookie is not sent over plaintext HTTP) |
| `DP_SESSION_IDLE_MINUTES` | `60` | Idle timeout |
| `DP_LOG_LEVEL` | `INFO` | Log level |
| `DP_TLS_VERIFY` | `0` | Keep at 0 for a PBX with a self-signed certificate |

Sessions live in process memory, so `--workers 1` is fixed; restarting the container means everyone logs in again.

---

## 5. Expose HTTPS with Cloudflare Tunnel

The container is at `192.0.2.230:8080`; just point the tunnel ingress at it (TLS is terminated by Cloudflare):

```yaml
# cloudflared config snippet
tunnel: <your tunnel id>
credentials-file: /root/.cloudflared/<tunnel id>.json
ingress:
  - hostname: dp-auto.example.com
    service: http://192.0.2.230:8080
  - service: http_status:404
```

If cloudflared runs in the **same** container, use `http://127.0.0.1:8080`.
Once it is pointed there, it is better to change `DP_COOKIE_SECURE` to `1` (HTTPS-only across the site is safer).

---

## 6. Upgrade / rollback

An OCI application container **cannot be upgraded by swapping the tag**; the way is "rebuild → recreate the container". This app is stateless,
so recreating it only means everyone logs in again:

```bash
# 1) Re-package on the dev machine and upload to /root/dp-auto-web-src.tar.gz
# 2) On the node:
SRC_TAR=/root/dp-auto-web-src.tar.gz UPGRADE=1 \
IMAGE_TAG=dp-auto-web:2.0.1 TEMPLATE_NAME=dp-auto-web_2.0.1.tar \
./pve-deploy-oci.sh
```

`UPGRADE=1` runs `pct stop` + `pct destroy` first, then recreates with the same parameters; to roll back, run it again with the old version number.
The template left by this deployment is at `/var/lib/vz/template/cache/dp-auto-web_2.0.0-alpha.1.tar`,
so it can be recreated at any time.

---

## 7. Troubleshooting (all pitfalls hit during this deployment)

| Symptom | Cause / fix |
|---|---|
| `pct exec <vmid> -- ...` **hangs** | An OCI application container has no init/tty, so `pct exec` is unavailable. Check service output instead: `pct console <vmid>`; verify with `curl http://<ip>:8080/api/health` |
| `pvesm path local:vztmpl` returns empty | `pvesm path` only accepts a **specific file**; given a directory it returns an empty string (which would drop the archive into `/`). To get the directory, read `path` from `/etc/pve/storage.cfg` and append `/template/cache` |
| `volume 'local:vztmpl/xxx.tar' does not exist` | The archive is not in the template directory. Put it under `<storage path>/template/cache/`; if `pveam list <storage>` shows it, it is in the right place |
| `pct create` does not print `Detected OCI archive` | What you have is not an OCI archive: make sure it was converted with `skopeo copy … oci-archive:` (a docker-archive from `docker save` is not recognized) |
| Login reports "cannot connect to the PBX" | Container outbound access / route to the PBX; try `curl -v https://<pbx>/` from the node |
| Login reports "TLS handshake failed" | First confirm `DP_TLS_VERIFY=0`. In testing, `deltapath-mbic.maxis.com.my` negotiated TLSv1.2 + ECDHE-RSA-AES256-GCM-SHA384, which the container's OpenSSL 3.x handles by default |
| Long-running pipelines get cut off by the reverse proxy | Increase the reverse proxy `proxy_read_timeout` (the app has long-lived SSE connections) |
| `vzdump` fails with **`CT is locked (mounted)`** | `pct mount <vmid>` (used by `deploy/diag-113.sh`) writes `lock: mounted` into `/etc/pve/lxc/<vmid>.conf`. If that script is interrupted before its `pct unmount`, the lock outlives the mount and **every** backup fails — the container itself is fine. Fix: `pct unmount <vmid>` then `pct unlock <vmid>` (or just `pct unlock`). `pve-deploy-oci.sh` now clears a stale mount lock before building and again before exiting; `diag-113.sh` unmounts from an `EXIT/INT/TERM` trap so it cannot leave one behind |

---

## 8. Alternatives for PVE < 9.1

### Option 1: Debian 12 LXC + venv + systemd

The node already has `local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst`:

```bash
pct create 113 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname dp-auto-web --memory 512 --cores 1 --rootfs sda_storage:4 \
  --net0 name=eth0,bridge=vmbr0,ip=192.0.2.230/24,gw=192.0.2.1 \
  --unprivileged 1 --onboot 1 --start 1

pct exec 113 -- bash -c "apt-get update && apt-get install -y python3-venv"
pct push 113 /root/dp-auto-web-src.tar.gz /root/src.tar.gz
pct exec 113 -- bash -c "mkdir -p /opt/dp-auto-web && tar -xzf /root/src.tar.gz -C /opt/dp-auto-web \
  && python3 -m venv /opt/dp-auto-web/.venv \
  && /opt/dp-auto-web/.venv/bin/pip install -r /opt/dp-auto-web/requirements.txt"
```

Then add a systemd unit (`ExecStart=/opt/dp-auto-web/.venv/bin/python -m uvicorn backend.app.main:app
--host 0.0.0.0 --port 8080 --workers 1`, `WorkingDirectory=/opt/dp-auto-web`) and
`systemctl enable --now dp-auto-web`.

### Option 2: LXC + Docker Compose

```bash
pct create 113 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname dp-auto-web --memory 1024 --cores 2 --rootfs sda_storage:4 \
  --net0 name=eth0,bridge=vmbr0,ip=192.0.2.230/24,gw=192.0.2.1 \
  --features nesting=1,keyctl=1 --unprivileged 1 --onboot 1 --start 1
# install docker inside the container, then docker compose up -d (the repo has docker-compose.yml)
```

---

## 9. What this deployment left behind

| Location | Content |
|---|---|
| `/var/lib/vz/template/cache/dp-auto-web_2.0.0-alpha.1.tar` | OCI template (60MB), used for rebuilds |
| `/etc/pve/lxc/113.conf` | Container config (with `entrypoint` and all `DP_*` environment variables) |
| Inside CT 103 | Build leftovers cleaned up, `dp-auto-web` image removed with `docker rmi` |
| Node `/root/` | Build source / context / image tars deleted |
