"""Deploy updated frontend and backend to Proxmox CT 113."""

import os
import sys
import time
from pathlib import Path
import paramiko

HOST = os.environ.get("PVE_HOST", "")
USER = os.environ.get("PVE_USER", "root")
PASSWORD = os.environ.get("PVE_PASS", "")
PORT = int(os.environ.get("PVE_PORT", "22"))

if not HOST or not PASSWORD:
    sys.exit("Set PVE_HOST / PVE_USER / PVE_PASS environment variables first.")

TAR_PATH = Path("update-ct113.tar.gz")

def main():
    if not TAR_PATH.exists():
        sys.exit(f"File {TAR_PATH} not found.")

    print(f"Connecting to PVE host {HOST}:{PORT} as {USER}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=HOST, port=PORT, username=USER, password=PASSWORD, timeout=20)

    def run_cmd(cmd: str):
        print(f"$ {cmd}")
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out.strip())
        if err.strip():
            print(f"[stderr] {err.strip()}")
        if code != 0:
            raise RuntimeError(f"Command failed with exit code {code}: {cmd}")
        return out

    try:
        print("\nStep 1: Create backup inside CT 113...")
        run_cmd("pct exec 113 -- /bin/sh -c 'BACKUP_DIR=/srv/app/.backups/backup-$(date +%Y%m%d-%H%M%S) && mkdir -p \"$BACKUP_DIR\" && cp -r /srv/app/frontend /srv/app/backend \"$BACKUP_DIR\" && echo Backup saved to $BACKUP_DIR'")

        print("\nStep 2: Upload update tarball to PVE host...")
        sftp = client.open_sftp()
        sftp.put(str(TAR_PATH), "/tmp/update-ct113.tar.gz")
        sftp.close()
        print("Uploaded /tmp/update-ct113.tar.gz")

        print("\nStep 3: Push update tarball into CT 113...")
        run_cmd("pct push 113 /tmp/update-ct113.tar.gz /srv/app/update-ct113.tar.gz --user dpauto --group dpauto")
        run_cmd("rm -f /tmp/update-ct113.tar.gz")

        print("\nStep 4: Extract update in CT 113 and fix ownership...")
        run_cmd("pct exec 113 -- /bin/sh -c 'tar -xzf /srv/app/update-ct113.tar.gz -C /srv/app && rm -f /srv/app/update-ct113.tar.gz && chown -R dpauto:dpauto /srv/app/backend /srv/app/frontend'")

        print("\nStep 5: Verify Python import inside CT 113...")
        run_cmd("pct exec 113 -- /bin/sh -c 'cd /srv/app && python -c \"import backend.app.main as m; print(\\\"IMPORT SUCCESS:\\\", m.app.title)\"'")

        print("\nStep 6: Reboot CT 113 to apply clean process reload...")
        run_cmd("pct reboot 113")

        print("\nStep 7: Wait for CT 113 to come back online...")
        for i in range(20):
            time.sleep(2)
            try:
                out = run_cmd("curl -s http://192.0.2.230:8080/api/health")
                if '"status":"ok"' in out:
                    print("Service is UP and HEALTHY!")
                    break
            except Exception as e:
                print(f"Waiting ({i+1}/20)... ({e})")
        else:
            print("Warning: Did not get ok status within 40 seconds.")

        print("\nStep 8: Check /api/pbx/contexts/all route status code...")
        code_out = run_cmd("curl -s -o /dev/null -w '%{http_code}' http://192.0.2.230:8080/api/pbx/contexts/all")
        print(f"/api/pbx/contexts/all HTTP code: {code_out}")

        print("\nStep 9: Check frontend file content timestamp/size in CT 113...")
        run_cmd("pct exec 113 -- ls -la /srv/app/frontend/js/views/pipeline-complex.js")

        print("\nUpdate completed successfully!")
    finally:
        client.close()

if __name__ == "__main__":
    main()
