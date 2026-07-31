#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root."
    exit 1
fi

apt-get update
apt-get install -y \
    ca-certificates \
    caddy \
    curl \
    git \
    gettext \
    libpq-dev \
    postgresql \
    postgresql-client \
    python3.13 \
    python3.13-dev \
    python3.13-venv \
    rclone \
    build-essential

if ! id jobapply >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /opt/jobapply --shell /bin/bash jobapply
fi

install -d -o jobapply -g jobapply -m 0750 /opt/jobapply
install -d -o jobapply -g jobapply -m 0700 /var/backups/jobapply

if ! command -v poetry >/dev/null 2>&1; then
    curl -sSL https://install.python-poetry.org | POETRY_HOME=/opt/poetry python3.13 -
    ln -sf /opt/poetry/bin/poetry /usr/local/bin/poetry
fi

if ! swapon --show=NAME --noheadings | grep -q .; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

systemctl enable --now postgresql caddy

echo "Base packages installed. Continue with deploy/vps/README.md."
