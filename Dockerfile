# syntax=docker/dockerfile:1
#
# Deltapath Automation —— 浏览器版
# 单服务镜像，可直接被 Proxmox VE 9.1+ 当作 OCI 应用容器（OCI-as-LXC）运行，
# 也可以普通 docker / podman run。
#
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# 依赖单独一层：只改业务代码时不必重装依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# 应用运行参数。Proxmox 里可在 CT 的 Options → Environment 增加
# lxc.environment.runtime 项来覆盖（见 deploy/proxmox-oci-lxc.md）。
ENV DP_APP_NAME="Anderson Deltapath-Automation" \
    DP_HOST=0.0.0.0 \
    DP_PORT=8080 \
    DP_LOG_LEVEL=INFO \
    DP_SESSION_IDLE_MINUTES=60 \
    DP_SESSION_ABSOLUTE_MINUTES=480 \
    DP_COOKIE_SECURE=0 \
    DP_TLS_VERIFY=0 \
    DP_TRUST_PROXY_HEADERS=0

# 非 root 运行
RUN useradd --create-home --uid 10001 dpauto \
 && chown -R dpauto:dpauto /srv/app
USER dpauto

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]

# 单 worker：会话保存在进程内存里（见 backend/app/sessions.py）
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--proxy-headers"]
