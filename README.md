# JobApply

**JobApply** is a Django-based job application tracker built around a **Google-first workflow**:
- **Google OAuth** is the only authentication method (no passwords).
- **Google Drive backups** are the flagship integration (CSV/XLSX export + restore-ready storage).
- **Google Calendar integration** is planned next (roadmap).

The project is designed for **dev-friendly, one-command startup via Docker Compose**.

---

## Why it exists (product pitch)

If you already live in Google Workspace, you don’t want another app with yet another password and a fragile export flow.
JobApply uses Google as the identity provider and (optionally) Google Drive as the storage layer for backups.

---

## Key features

- **Google-only sign-in** (django-allauth)
- **Optional Google Drive connection**
  - Create `JobApply/` folder (and optional `backups/` subfolder)
  - Upload backups (CSV/XLSX)
  - List & download backup files
  - Disconnect Drive (revoke local tokens / unlink)
- Applications CRUD with statuses + filters
- Interview planner (linked to applications)
- Reports: local import/export + statistics
- Terms/consent gate for data processing (first-time user flow)

---

## Tech stack

- **Python 3.14** (container image: `python:3.14-rc-slim`)
- **Django 5+**
- **PostgreSQL 18**
- **Docker Compose v2** (`docker compose ...`)
- **Poetry** for dependency management (installed in container)
- Google integrations:
  - **django-allauth** (OAuth)
  - **Google Drive API** via `google-api-python-client`

---

## Quick start (Docker, dev mode)

### 1) Prereqs
- Docker + Docker Compose v2 installed
- A Google Cloud project with OAuth credentials (see below)

### 2) Configure env
Create a `.env` file next to `docker-compose.yml` (you can start from `.env.example`):

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

POSTGRES_DB=jobapply
POSTGRES_USER=jobapply
POSTGRES_PASSWORD=jobapply
POSTGRES_HOST=db
POSTGRES_PORT=5432

DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=admin12345

# Google OAuth (django-allauth)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
DJANGO_SITE_DOMAIN=0.0.0.0:8000
DJANGO_SITE_NAME=JobApply
```

### 3) Start the stack
```bash
docker compose up --build
```

The web app will be available at:
- http://localhost:8000

**Important:** the container entrypoint is dev-friendly and does the plumbing for you:
- waits for DB
- runs migrations (when `DJANGO_AUTOMIGRATE=1`)
- creates/updates Google SocialApp from env (idempotent)
- creates superuser from env (idempotent)
- starts Django dev server
---

## Docker entrypoint script (important)

The container uses a **dev-friendly entrypoint** (`entrypoint.sh`) to make local setup painless. fileciteturn1file0

What it does, in order:

1. **Installs dependencies** inside the container:
   - `poetry install --no-interaction --no-ansi`
2. **Waits for PostgreSQL** to accept connections (up to ~60 seconds):
   - Uses `psycopg` to open/close a connection using `POSTGRES_*` env vars.
3. **(Optional) Auto-makemigrations for development**
   - Only if `DJANGO_AUTOMIGRATE=1`
   - Runs `python manage.py makemigrations --noinput`
4. **Runs migrations**
   - `python manage.py migrate --noinput`
5. **Creates Google SocialApp from env (idempotent)**
   - `python manage.py create_google_socialapp_if_not_exists`
   - This wires up `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` automatically.
6. **Creates a Django superuser from env (idempotent)**
   - `python manage.py create_superuser_if_not_exists`
7. **Starts Django dev server**
   - `python manage.py runserver 0.0.0.0:8000`

### Env flags used by the entrypoint
- `DJANGO_AUTOMIGRATE=1` — runs `makemigrations` on startup (DEV only; don’t use in prod)
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — DB connection
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — used by the SocialApp creation command
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` — superuser creation

**Why this matters:** it turns “clone → docker compose up” into a predictable, repeatable workflow (no manual migrations / admin creation / social app setup).


---

## Google OAuth setup (mandatory)

### A) Create OAuth credentials
In **Google Cloud Console**:
1. Create / select a project
2. Configure **OAuth consent screen**
3. Create **OAuth client ID** (Web application)
4. Add **Authorized redirect URI**:

```text
http://localhost:8000/accounts/google/login/callback/
```

> If you run behind a custom domain later, add its callback URL too.

### B) Put credentials into `.env`
Set:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

### C) Login entry points
This project is intentionally Google-first:
- `/` redirects to Google login (oauth2_login)
- `/accounts/login/` is also forced to Google login

---

## Google Drive integration (flagship feature)

### 1) Enable the Google Drive API (mandatory for backups)
In Google Cloud Console:
- **APIs & Services → Library → Google Drive API → Enable**

If Drive API is not enabled, you can still sign in, but Drive operations will fail.

### 2) How “Connect Drive” works
Drive access is **opt-in** at the UI level:
- User logs in with Google
- User clicks **Connect Google Drive**
- App runs allauth connect flow (`process=connect`) and stores tokens
- Backups become available under **Reports → Cloud backups**

### 3) Drive scope
The app uses the `drive.file` scope:
- `https://www.googleapis.com/auth/drive.file`

This is the minimal scope required for app-managed uploads in the user’s Drive.

---

## Local admin

Django admin:
- http://localhost:8000/admin/

Credentials are created from `.env`:
- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`

---

## Useful commands (Docker)

### Open a shell in the web container
```bash
docker compose exec web bash
```

### Run Django management commands
```bash
docker compose exec web poetry run python manage.py <command>
```

### Reset everything (⚠️ deletes DB volume)
```bash
docker compose down --remove-orphans -v
```

---

## Fixtures (dev test data)

Upload fixtures into the DB and assign them to your Google user:

```bash
docker compose exec web python manage.py loaddata fixtures/applications.json   && docker compose exec web python manage.py assign_fixtures_owner --email you-google-email@gmail.com --from-user-id 1
```

Dry-run verification:
```bash
docker compose exec web python manage.py assign_fixtures_owner --email you-google-email@gmail.com --from-user-id 1 --dry-run
```

---

## Roadmap (next integration)

- Google Calendar integration (create interview events, reminders, sync)
- Stronger backup/restore workflows (one-click restore)

**Author:** Maksym Petrykin  
Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)  
Telegram: [@max_p95](https://t.me/max_p95)
