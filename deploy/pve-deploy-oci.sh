#!/usr/bin/env bash
#
# On a Proxmox VE node, deploy this repo as an **OCI application container** (OCI-as-LXC).
#
# Verified on a PVE 9.2.21 / Debian 13 node (DP Auto Web 2.0.0-alpha.1).
#
# Usage (on the node; the source tar must be uploaded to $SRC_TAR first):
#     SRC_TAR=/root/dp-auto-web-src.tar.gz ./pve-deploy-oci.sh
#     SRC_TAR=... UPGRADE=1 ./pve-deploy-oci.sh          # rebuild (upgrade)
#
# Every parameter can be overridden by an env var; the defaults are the values used in this verified deployment.
#
set -uo pipefail

# ---- Target container ----
VMID=${VMID:-113}
NAME=${NAME:-dp-auto-web}
IP_CIDR=${IP_CIDR:-192.0.2.230/24}
GATEWAY=${GATEWAY:-192.0.2.1}
STORAGE=${STORAGE:-sda_storage}          # storage holding the container rootfs
TEMPLATE_STORAGE=${TEMPLATE_STORAGE:-local}   # storage for the OCI template (must support vztmpl)
MEMORY=${MEMORY:-512}
CORES=${CORES:-1}
DISK=${DISK:-4}
PORT=${PORT:-8080}
BRIDGE=${BRIDGE:-vmbr0}

# ---- Image ----
SRC_TAR=${SRC_TAR:-/root/dp-auto-web-src.tar.gz}
IMAGE_TAG=${IMAGE_TAG:-dp-auto-web:2.0.0-alpha.1}
TEMPLATE_NAME=${TEMPLATE_NAME:-dp-auto-web_2.0.0-alpha.1.tar}
BUILD_CT=${BUILD_CT:-}                   # empty = auto-pick a container with docker; or build on the node with BUILD_ON=node
BUILD_ON=${BUILD_ON:-auto}               # auto | node | ct

# ---- App environment variables ----
DP_TRUST_PROXY_HEADERS=${DP_TRUST_PROXY_HEADERS:-1}   # enable behind Cloudflare Tunnel / reverse proxy
DP_COOKIE_SECURE=${DP_COOKIE_SECURE:-0}               # set to 1 when accessed over HTTPS only
DP_DEFAULT_BASE_URL=${DP_DEFAULT_BASE_URL:-}
DP_SESSION_IDLE_MINUTES=${DP_SESSION_IDLE_MINUTES:-60}
DP_LOG_LEVEL=${DP_LOG_LEVEL:-INFO}
# The container defaults to UTC, so audit log / CSV times would be hours off -- inject the local timezone
TZ=${TZ:-Asia/Kuala_Lumpur}
# Audit log persistence: empty = memory only; a path appends JSONL (needs a mounted volume)
DP_AUDIT_FILE=${DP_AUDIT_FILE:-}

UPGRADE=${UPGRADE:-0}

log()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------- Lock hygiene
# `pct mount <vmid>` (used by diagnostics such as deploy/diag-113.sh) writes
# `lock: mounted` into /etc/pve/lxc/<vmid>.conf. If that script is interrupted, or a
# `pct unmount` is skipped, the lock outlives the mount and every later vzdump fails
# with "CT is locked (mounted)" -- the container itself is perfectly healthy.
#
# Note: `pct mount` succeeds even on a *running* container, so "the CT is running"
# is NOT proof that the lock is stale. Staleness is decided by the active-task check
# below; this only ever clears a `mounted` lock (never backup/restore/clone/etc.).
clear_stale_mount_lock() {
  local vmid="$1"
  local conf="/etc/pve/lxc/${vmid}.conf"
  [ -f "$conf" ] || return 0

  local lock
  lock=$(sed -n 's/^lock: *//p' "$conf" | head -1 | tr -d '\r')
  [ -n "$lock" ] || return 0

  if [ "$lock" != "mounted" ]; then
    warn "CT $vmid holds lock '$lock' (not a stale mount lock) -- leaving it alone"
    return 0
  fi

  # A live task (backup, restore, clone, migration, ...) owns its lock: never race it.
  local node active
  node=$(hostname)
  active=$(pvesh get "/nodes/$node/tasks" --vmid "$vmid" --source active \
             --output-format json 2>/dev/null | tr -d '[]", \n')
  if [ -n "$active" ]; then
    warn "CT $vmid has an active task ($active) -- not clearing its lock"
    return 0
  fi

  # No active task: a leftover `mounted` lock is stale. Release the mount first
  # (harmless when there is nothing mounted), then drop the lock.
  warn "Clearing stale 'mounted' lock on CT $vmid (left behind by pct mount)"
  pct unmount "$vmid" >/dev/null 2>&1 || true
  pct unlock "$vmid" >/dev/null 2>&1 || true

  if sed -n 's/^lock: *//p' "$conf" | grep -q .; then
    warn "Could not clear the lock on CT $vmid; check $conf manually"
  else
    log "Lock on CT $vmid cleared"
  fi
}

[ "$(id -u)" -eq 0 ] || die "Please run as root on a Proxmox node"
command -v pct >/dev/null || die "pct not found; this does not look like a PVE node"
[ -f "$SRC_TAR" ] || die "Source tarball $SRC_TAR not found (tar it on the dev machine and upload it)"

# ---------------------------------------------------------------- Pick build environment
pick_build_ct() {
  if [ -n "$BUILD_CT" ]; then echo "$BUILD_CT"; return; fi
  for ct in $(pct list | awk 'NR>1 && $2=="running" {print $1}'); do
    if pct exec "$ct" -- docker --version >/dev/null 2>&1; then
      echo "$ct"; return
    fi
  done
  echo ""
}

# -------------------------------------------------------------------- Smoke test
# Before deploying, hit /api/health once in a throwaway container: problems like
# "a missing field in config.py crashes startup" are caught here, with no impact on the live container.
SMOKE_PORT=${SMOKE_PORT:-18080}
SMOKE_NAME=dp-auto-web-smoke

smoke_test_image() {
  local runner="$1"   # "node" or a container vmid
  local docker="docker"
  [ "$runner" != "node" ] && docker="pct exec $runner -- docker"

  log "Image smoke test (throwaway container hits /api/health)"
  $docker rm -f "$SMOKE_NAME" >/dev/null 2>&1

  if ! $docker run -d --name "$SMOKE_NAME" "$IMAGE_TAG" >/dev/null 2>&1; then
    warn "Throwaway container did not start; logs:"
    $docker logs --tail 30 "$SMOKE_NAME" 2>&1 | sed 's/^/    /' || true
    $docker rm -f "$SMOKE_NAME" >/dev/null 2>&1
    die "Smoke test failed: the image cannot start; deployment aborted (live container untouched)"
  fi

  local ok=0
  for _ in $(seq 1 15); do
    if $docker exec "$SMOKE_NAME" python -c \
        "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).status == 200 else 1)" \
        >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 2
  done

  if [ "$ok" != "1" ]; then
    warn "Health check did not pass; container logs (last 30 lines):"
    $docker logs --tail 30 "$SMOKE_NAME" 2>&1 | sed 's/^/    /' || true
    $docker rm -f "$SMOKE_NAME" >/dev/null 2>&1
    die "Smoke test failed: the service cannot start; deployment aborted (live container untouched)"
  fi

  $docker rm -f "$SMOKE_NAME" >/dev/null 2>&1
  log "Smoke test passed"
}

# -------------------------------------------------------------------- Build
build_image() {
  log "Unpacking source"
  rm -rf /root/dp-auto-web-build && mkdir -p /root/dp-auto-web-build
  tar -xzf "$SRC_TAR" -C /root/dp-auto-web-build
  tar -czf /root/dp-auto-web-context.tar.gz -C /root/dp-auto-web-build .

  local target="$BUILD_ON"
  if [ "$target" = "auto" ]; then
    if command -v docker >/dev/null 2>&1; then target=node; else target=ct; fi
  fi

  if [ "$target" = "node" ]; then
    log "Running docker build on the node"
    docker build -t "$IMAGE_TAG" /root/dp-auto-web-build || die "docker build failed"
    smoke_test_image node
    docker save -o /root/dp-auto-web-image.tar "$IMAGE_TAG" || die "docker save failed"
  else
    local ct; ct=$(pick_build_ct)
    [ -n "$ct" ] || die "No container with docker found; set BUILD_CT=<vmid> or install docker on the node first"
    log "Building the image with borrowed container $ct"
    pct exec "$ct" -- rm -rf /root/dpbuild /root/dp-auto-web-context.tar.gz /root/dp-auto-web-image.tar 2>/dev/null
    pct push "$ct" /root/dp-auto-web-context.tar.gz /root/dp-auto-web-context.tar.gz
    pct exec "$ct" -- mkdir -p /root/dpbuild
    pct exec "$ct" -- tar -xzf /root/dp-auto-web-context.tar.gz -C /root/dpbuild
    pct exec "$ct" -- docker build -t "$IMAGE_TAG" /root/dpbuild || die "docker build failed"
    smoke_test_image "$ct"
    pct exec "$ct" -- docker save -o /root/dp-auto-web-image.tar "$IMAGE_TAG" || die "docker save failed"
    pct pull "$ct" /root/dp-auto-web-image.tar /root/dp-auto-web-image.tar || die "pct pull failed"
    pct exec "$ct" -- rm -rf /root/dpbuild /root/dp-auto-web-context.tar.gz /root/dp-auto-web-image.tar
    pct exec "$ct" -- docker rmi "$IMAGE_TAG" >/dev/null 2>&1
  fi
  rm -f /root/dp-auto-web-context.tar.gz
  log "Image exported: $(ls -lh /root/dp-auto-web-image.tar | awk '{print $5}')"
}

# ------------------------------------------------- Convert to OCI archive and place in the template dir
make_template() {
  # Note: pvesm path only accepts a concrete file; given a directory it returns an empty string (learned the hard way)
  local storage_path cache
  storage_path=$(awk -v s="$TEMPLATE_STORAGE" '$1=="dir:" && $2==s {getline; print $2; exit}' /etc/pve/storage.cfg)
  [ -n "$storage_path" ] || die "Cannot read the path of storage $TEMPLATE_STORAGE"
  cache="$storage_path/template/cache"
  mkdir -p "$cache"

  log "skopeo: docker-archive -> oci-archive"
  rm -f "$cache/$TEMPLATE_NAME"
  skopeo copy "docker-archive:/root/dp-auto-web-image.tar" "oci-archive:$cache/$TEMPLATE_NAME" \
    || die "skopeo conversion failed (the node needs skopeo: apt-get install -y skopeo)"
  log "Template: $cache/$TEMPLATE_NAME"
  TEMPLATE_REF="$TEMPLATE_STORAGE:vztmpl/$TEMPLATE_NAME"
}

# ------------------------------------------------------------------ Create container
free_leftovers() {
  for vol in $(pvesm list "$STORAGE" 2>/dev/null | awk -v v="$VMID" '$0 ~ ("/" v "/") {print $1}'); do
    warn "Freeing leftover volume $vol"
    pvesm free "$vol" || true
  done
}

create_container() {
  if pct status "$VMID" >/dev/null 2>&1; then
    [ "$UPGRADE" = "1" ] || die "VMID $VMID already exists; add UPGRADE=1 to rebuild"
    log "Destroying old container $VMID"
    pct stop "$VMID" 2>/dev/null; sleep 2
    # A previous `pct mount` (diagnostics) leaves the CT mounted/locked, which makes
    # destroy fail with "CT is locked (mounted)" -- clear both first.
    clear_stale_mount_lock "$VMID"
    pct unmount "$VMID" 2>/dev/null || true
    pct unlock "$VMID" 2>/dev/null || true
    pct destroy "$VMID" || die "pct destroy failed"
    free_leftovers
  fi

  log "Creating container $VMID from the OCI archive"
  pct create "$VMID" "$TEMPLATE_REF" \
    --hostname "$NAME" \
    --memory "$MEMORY" --cores "$CORES" --swap 256 \
    --rootfs "$STORAGE:$DISK" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=$IP_CIDR,gw=$GATEWAY" \
    --nameserver 1.1.1.1 \
    --unprivileged 1 \
    --onboot 1 || die "pct create failed"

  grep -q '^entrypoint:' "/etc/pve/lxc/$VMID.conf" \
    || warn "No entrypoint in the config -- it may not have been detected as an OCI image; check whether the pct create output contains 'Detected OCI archive'"
}

inject_env() {
  log "Injecting environment variables"
  local conf="/etc/pve/lxc/$VMID.conf"
  sed -i '/lxc.environment.runtime: DP_TRUST_PROXY_HEADERS=/d;
          /lxc.environment.runtime: DP_COOKIE_SECURE=/d;
          /lxc.environment.runtime: DP_SESSION_IDLE_MINUTES=/d;
          /lxc.environment.runtime: DP_LOG_LEVEL=/d;
          /lxc.environment.runtime: DP_AUDIT_FILE=/d;
          /lxc.environment.runtime: TZ=/d;
          /lxc.environment.runtime: DP_DEFAULT_BASE_URL=/d' "$conf"
  {
    echo "lxc.environment.runtime: TZ=$TZ"
    echo "lxc.environment.runtime: DP_TRUST_PROXY_HEADERS=$DP_TRUST_PROXY_HEADERS"
    echo "lxc.environment.runtime: DP_COOKIE_SECURE=$DP_COOKIE_SECURE"
    echo "lxc.environment.runtime: DP_SESSION_IDLE_MINUTES=$DP_SESSION_IDLE_MINUTES"
    echo "lxc.environment.runtime: DP_LOG_LEVEL=$DP_LOG_LEVEL"
    [ -n "$DP_AUDIT_FILE" ] && echo "lxc.environment.runtime: DP_AUDIT_FILE=$DP_AUDIT_FILE"
    [ -n "$DP_DEFAULT_BASE_URL" ] && echo "lxc.environment.runtime: DP_DEFAULT_BASE_URL=$DP_DEFAULT_BASE_URL"
  } >> "$conf"
}

verify() {
  local ip="${IP_CIDR%%/*}"
  log "Starting container"
  pct start "$VMID" 2>/dev/null || true

  log "Waiting for $ip:$PORT/api/health (up to 60 seconds)"
  for _ in $(seq 1 30); do
    if [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://$ip:$PORT/api/health")" = "200" ]; then
      curl -s -m 5 "http://$ip:$PORT/api/health"; echo
      curl -s -m 5 -o /dev/null -w "    Homepage HTTP %{http_code}\n" "http://$ip:$PORT/"
      curl -s -m 5 -o /dev/null -w "    Unauthenticated /api/pbx/probe HTTP %{http_code} (should be 401)\n" "http://$ip:$PORT/api/pbx/probe"
      log "Access URL: http://$ip:$PORT"
      log "Point Cloudflare Tunnel at: http://$ip:$PORT"
      return 0
    fi
    sleep 2
  done
  warn "Did not come up within 60 seconds. Troubleshooting:"
  echo "    pct console $VMID          # see service output (app containers have no init, so do not use pct exec)"
  echo "    pct status $VMID"
  echo "    cat /etc/pve/lxc/$VMID.conf"
  return 1
}

# --------------------------------------------------------------------- Main flow
[ -n "${TEMPLATE_REF:-}" ] || true
log "PVE: $(pveversion | head -1)"
clear_stale_mount_lock "$VMID"      # a lock from an earlier interrupted run would block pct destroy
build_image
make_template
create_container
inject_env
verify
clear_stale_mount_lock "$VMID"      # belt and braces: leave the CT unlocked so vzdump can run
log "Done."
