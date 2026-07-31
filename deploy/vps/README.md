# JobApply: no-Docker VPS deployment

Target: a personal 1 GB RAM VPS with 2 GB swap, local PostgreSQL, Caddy, Gunicorn and systemd.

Detailed architecture and optimization rationale are in `DEPLOYMENT_ARCHITECTURE.txt`.

## Layout

- application: `/opt/jobapply`
- virtualenv: `/opt/jobapply/.venv`
- environment: `/opt/jobapply/.env`
- local backups: `/var/backups/jobapply`
- Caddy domain: replace `jobapply.p95max.dev` in `Caddyfile`

## 1. Prepare the server

Use Debian 12 or Ubuntu 24.04. Clone the repository temporarily or copy the deployment directory, then run as root:

```bash
bash deploy/vps/install.sh
```

The script installs PostgreSQL, Caddy, Poetry, rclone and `uv`. Python 3.13 is installed through `uv`, avoiding dependence on the distribution's Python package version. It also creates the `jobapply` system user and a 2 GB swap file when no swap exists.

## 2. Configure PostgreSQL

```bash
sudo -u postgres createuser jobapply
sudo -u postgres createdb -O jobapply jobapply
sudo -u postgres psql -c "ALTER USER jobapply WITH PASSWORD 'replace-this-password';"
```

For a 1 GB server, add these values to the active `postgresql.conf`:

```conf
shared_buffers = 64MB
effective_cache_size = 256MB
work_mem = 2MB
maintenance_work_mem = 32MB
max_connections = 20
```

Restart PostgreSQL afterwards.

## 3. Install JobApply

```bash
sudo -u jobapply git clone https://github.com/p95max/JobApply.git /opt/jobapply
cd /opt/jobapply
sudo -u jobapply git checkout agent/vps-no-docker-deploy
sudo -u jobapply poetry config virtualenvs.in-project true
sudo -u jobapply poetry env use "$(sudo -u jobapply -H uv python find 3.13)"
sudo -u jobapply poetry install --only main --no-interaction
sudo -u jobapply poetry run pip install gunicorn==23.0.0
sudo -u jobapply cp deploy/vps/jobapply.env.example .env
sudo -u jobapply nano .env
sudo chown jobapply:jobapply .env
sudo chmod 600 .env
```

Gunicorn is installed into the project virtualenv without modifying the application lock file. This deployment branch only adds infrastructure configuration.

## 4. Django initialization

```bash
cd /opt/jobapply
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py migrate --noinput
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py collectstatic --noinput
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py create_google_socialapp_if_not_exists
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py create_superuser_if_not_exists
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py check --deploy
```

## 5. Install services

Use the Argus-style installer rather than copying units manually:

```bash
cd /opt/jobapply
chmod +x deploy/vps/install-ops.sh deploy/vps/scripts/*.sh
./deploy/vps/install-ops.sh
```

The installer copies versioned scripts to `/usr/local/bin`, installs systemd units, validates Caddy and enables the services and timers.

The Neon timer safely skips its run when `BACKUP_DATABASE_URL` is empty.

## 6. Configure Google Drive backup

Run the interactive rclone setup as the application user:

```bash
sudo -u jobapply -H rclone config
```

Create a remote named `gdrive`. Daily dumps are copied to:

```text
gdrive:JobApply/database-backups/
```

The local retention is seven days. Google Drive stores the historical off-site copies.

## 7. Configure Neon warm copy

Create a dedicated free Neon project used only as a recovery copy. Put its direct PostgreSQL connection string in `BACKUP_DATABASE_URL` in `.env`.

Every Sunday the local database is dumped and restored to Neon with `--clean`, `--if-exists`, `--single-transaction` and migration-count verification. Never point this variable at a production database or a pooled Neon endpoint.

## Operations

```bash
systemctl status jobapply-web jobapply-gmail-worker
journalctl -u jobapply-web -f
journalctl -u jobapply-gmail-worker -f
systemctl start jobapply-backup.service
systemctl start jobapply-neon-sync.service
systemctl list-timers --all | grep jobapply
```

## Deployment update

```bash
cd /opt/jobapply
git pull --ff-only
sudo -u jobapply poetry install --only main --no-interaction
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py migrate --noinput
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py collectstatic --noinput
./deploy/vps/install-ops.sh
systemctl restart jobapply-web jobapply-gmail-worker
```

## Recovery

```bash
sudo -u postgres dropdb --if-exists jobapply
sudo -u postgres createdb -O jobapply jobapply
sudo -u jobapply pg_restore --no-owner --no-acl --dbname=jobapply /var/backups/jobapply/jobapply_TIMESTAMP.dump
```

Test recovery periodically. A backup that has never been restored is not verified.