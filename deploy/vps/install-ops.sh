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
sudo install -o root -g jobapply -m 0750 deploy/vps/jobapply-deploy.sh /usr/local/sbin/jobapply-deploy
sudo install -o root -g jobapply -m 0750 deploy/vps/jobapply-deploy-notify.sh "$BIN_DIR/jobapply-deploy-notify.sh"
sudo install -m 0440 deploy/vps/sudoers/jobapply-telegram /etc/sudoers.d/jobapply-telegram
sudo visudo -cf /etc/sudoers.d/jobapply-telegram
sudo install -m 0644 deploy/vps/Caddyfile "$CADDY_FILE"

sudo install -d -o jobapply -g jobapply -m 0700 /var/backups/jobapply

# Caddy serves collected static and uploaded media directly. The application
# directory is intentionally not world-readable, so grant Caddy access through
# the existing jobapply group and normalize only the public asset trees.
if id caddy >/dev/null 2>&1; then
    sudo usermod -aG jobapply caddy
fi

# The Gmail Assistant token-usage page reads only retained JobApply service
# entries from journald. Membership takes effect after the web service restart.
if getent group systemd-journal >/dev/null 2>&1; then
    sudo usermod -aG systemd-journal jobapply
fi

sudo chown jobapply:jobapply "$PROJECT_DIR"
sudo chmod 0750 "$PROJECT_DIR"
for asset_dir in "$PROJECT_DIR/staticfiles" "$PROJECT_DIR/media"; do
    if [[ -d "$asset_dir" ]]; then
        sudo chown -R jobapply:jobapply "$asset_dir"
        sudo find "$asset_dir" -type d -exec chmod 0750 {} +
        sudo find "$asset_dir" -type f -exec chmod 0640 {} +
    fi
done

sudo systemctl daemon-reload
sudo systemctl enable --now jobapply-web.service jobapply-gmail-worker.service
sudo systemctl enable --now jobapply-backup.timer jobapply-neon-sync.timer
sudo caddy validate --config "$CADDY_FILE"
# Restart so Caddy and JobApply receive their updated supplementary groups.
sudo systemctl restart caddy jobapply-web.service jobapply-gmail-worker.service

systemctl status jobapply-web.service --no-pager -l
systemctl status jobapply-gmail-worker.service --no-pager -l
systemctl list-timers --all | grep jobapply || true

echo "Installed JobApply no-Docker VPS operations files."
