#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/jobapply}"
SYSTEMD_DIR="/etc/systemd/system"
BIN_DIR="/usr/local/bin"
CADDY_FILE="/etc/caddy/Caddyfile"

cd "$PROJECT_DIR"

[[ -d deploy/vps/systemd ]] || { echo "ERROR: deploy/vps/systemd not found"; exit 1; }
[[ -d deploy/vps/scripts ]] || { echo "ERROR: deploy/vps/scripts not found"; exit 1; }

sudo install -m 0644 deploy/vps/systemd/jobapply-*.service deploy/vps/systemd/jobapply-*.timer "$SYSTEMD_DIR/"
sudo install -o root -g jobapply -m 0750 deploy/vps/scripts/jobapply-* "$BIN_DIR/"
sudo install -m 0644 deploy/vps/Caddyfile "$CADDY_FILE"

sudo install -d -o jobapply -g jobapply -m 0700 /var/backups/jobapply
sudo systemctl daemon-reload
sudo systemctl enable --now jobapply-web.service jobapply-gmail-worker.service
sudo systemctl enable --now jobapply-backup.timer jobapply-neon-sync.timer
sudo caddy validate --config "$CADDY_FILE"
sudo systemctl reload caddy

systemctl status jobapply-web.service --no-pager -l
systemctl status jobapply-gmail-worker.service --no-pager -l
systemctl list-timers --all | grep jobapply || true

echo "Installed JobApply no-Docker VPS operations files."
