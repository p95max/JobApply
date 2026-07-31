# JobApply

[![CI](https://github.com/p95max/JobApply/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/JobApply/actions/workflows/ci.yml)

---

**JobApply** is a focused Django job application tracker built around a **Google-first workflow**. It avoids feature bloat and unnecessary AI, providing only the tools needed to manage applications, process Gmail responses, plan interviews, and maintain backups.

- **Google OAuth** is the only authentication method (no passwords).
- **Google Drive backups** provide automated, rotation-based cloud backups.
- **Gmail Assistant (read-only)** turns relevant Gmail messages into reviewable application and interview suggestions.
- **Google Calendar integration**  #TODO .

The project is designed for **dev-friendly, one-command startup via Docker Compose**.

---

## Why it exists (product pitch)

If you already live in Google Workspace, you don’t want another app with yet another password and a fragile export flow.
JobApply uses Google as the identity provider and (optionally) Google Drive as the storage layer for backups.

---

## Key features

- **Google-only sign-in** (django-allauth)
- **Printable & PDF-Ready Applications Dashboard with Filters and Sorting**
- **Gmail Assistant** syncs, classifies and matches job-related emails, then creates suggestions that a user reviews before anything changes.
- **Optional Google Drive connection**
  - Create `JobApply/` folder (and optional `backups/` subfolder)
  - Upload backups (CSV/XLSX)
  - List & download backup files
  - Disconnect Drive (revoke local tokens / unlink)
  - **OPTIONAL** Auto Backup to Google Drive (latest + 2 retention)
  
- Applications CRUD with statuses + filters
- Interview planner (linked to applications)
- Services: local import/export + statistics
- Terms/consent gate for data processing (first-time user flow)

- **Cloudflare Turnstile**
  - Anti-bot gate before Google OAuth
  - Applied to anonymous users only (never shown to authenticated users)


---

## Tech stack

- **Python 3.14** (container image: `python:3.14-rc-slim`)
- **Django 5+**
- **PostgreSQL 18**
- **Docker Compose v2** (`docker compose ...`)
- **Poetry** for dependency management (installed in container)
- **Pytest**
- Google integrations:
  - **django-allauth** for OAuth authentication
  - **Google Drive API** via `google-api-python-client`
  - **Gmail API** via `google-api-python-client` (read-only statistics and Assistant sync)
  - **Cloudflare Turnstile** for pre-authentication bot protection
  - 
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

# Cloudflare Turnstile (anti-bot gate before Google OAuth)
TURNSTILE_ENABLED=1
TURNSTILE_SITE_KEY=...
TURNSTILE_SECRET_KEY=...

# Gmail Assistant
# Global AI capability; the user still has to opt in in the UI.
GMAIL_ASSISTANT_AI_ENABLED=0
OPENAI_API_KEY=...
OPENAI_EMAIL_MODEL=gpt-4.1-mini
# Background check for users who enabled AI analysis (15 minutes).
GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=1
GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS=900

# Hide admin behind a custom URL (optional)
ADMIN_URL=admin
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

- `/`  
  - authenticated users are redirected directly to the application  
  - anonymous users are redirected to the Turnstile gate

- `/accounts/google/login/`  
  Turnstile gate for anonymous users only (runs once per session, `never shown to authenticated users`)

- `/accounts/google/oauth/`  
  Starts Google OAuth flow after successful Turnstile verification

- `/accounts/login/`  
  Always redirected to the same Turnstile gate (Google-only authentication)


---

## Google Drive integration (flagship feature)

### 1) Enable the Google Drive/Gmail API (mandatory for backups and analytics)
In Google Cloud Console:
- **Your Project → APIs & Services → Library → Google Drive API → Enable**
- **Your Project → APIs & Services → Library → Gmail API → Enable**

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

### Auto Backup (Google Drive)

JobApply can run **automatic backups to Google Drive** on a schedule.

- **Runs every 5 minutes** (background worker)
- Stores backups in your Drive under `JobApply/backups/`
- **Retention policy:** keeps only **3 files**:
  - `latest.xlsx` (most recent)
  - `backup-1.xlsx`
  - `backup-2.xlsx`
- **Rotation logic** on each run:
  - `backup-2` is removed
  - `backup-1 → backup-2`
  - `latest → backup-1`
  - a new backup is uploaded as `latest`
- **Per-user isolation:** each user can enable/disable auto backup independently
- Requires Google Drive connection with **offline access** (`refresh_token`) and the **Drive API enabled** in Google Cloud Console

> The feature is optional and controlled via the **Cloud Backups** toggle in the UI.

---

### Gmail Statistics and Gmail Assistant (Read-Only)

JobApply has two Gmail services under **Services**:

- **Gmail stats** provides aggregate counts for replies, rejections, interview invites and auto-acknowledgements.
- **Gmail Assistant** turns relevant messages into reviewable suggestions for applications and interviews.

#### Gmail Assistant workflow

1. Connect the Google account whose mailbox you want to use. The consent request must include `gmail.readonly`; Gmail API must be enabled in Google Cloud Console.
2. Open **Services → Gmail Assistant** and use **Sync Gmail** to import candidate messages.
3. Optionally enable **AI analysis**. This is disabled by default and records a per-user consent timestamp. With the default settings, the first opt-in also starts a sync.
4. Review each pending proposal. You can accept it, edit and accept, choose another application, reject it or ignore it.

The Assistant can suggest creating an application, updating an application status, recording a recruiter reply, creating/updating/cancelling an interview, or an action that needs manual completion. **It never applies a proposal automatically.**

When `GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=1`, the `gmail-assistant-worker` checks opted-in users at `GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS` (900 seconds by default). Automatic checks only create pending proposals; they never change applications or interviews by themselves.

#### Privacy and failure behavior

- Gmail access is strictly read-only: the app never sends, deletes, archives, labels, or follows links in email.
- Attachments are not sent to OpenAI and full email bodies are not stored in `GmailMessage`.
- AI receives only sanitized subject, sender metadata and bounded text, and only after explicit opt-in plus `GMAIL_ASSISTANT_AI_ENABLED=1` and a configured `OPENAI_API_KEY`.
- Without an OpenAI key, the Assistant continues in rule-only mode.
- Gmail/OpenAI errors are isolated to the relevant sync/message and do not apply changes or expose OAuth/API details in the UI.
- Classifications and matching are suggestions, not guarantees; review every proposal before accepting it.


---

## Local admin

Admin is optionally exposed under a custom path via `ADMIN_URL`.

Example:  
If `ADMIN_URL=admin`, the admin panel is available at  
`http://localhost:8000/admin/`.

If `ADMIN_URL` is not set, the admin route is not registered.

Superuser credentials are configured via `.env`:
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

### Check the Gmail Assistant worker
```bash
docker compose logs -f gmail-assistant-worker
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
## Testing (pytest)

- Run the full quality gate
```bash
docker compose exec web poetry run pytest -ra -vv
docker compose exec web poetry run ruff check .
docker compose exec web poetry run python manage.py check
docker compose exec web poetry run python manage.py makemigrations --check --dry-run
```

### Migration verification

Verify the current development database without changing its application data:

```bash
docker compose exec -T web poetry run python manage.py migrate --plan
docker compose exec -T web poetry run python manage.py migrate --noinput
docker compose exec -T web poetry run python manage.py showmigrations gmail_stats
```

To verify a clean database, use a separate Compose project. It creates the
temporary `jobapply-migration-check` volume only; the final command removes
that temporary volume and leaves the regular `jobapply` database untouched.

```bash
docker compose -p jobapply-migration-check up -d db
docker compose -p jobapply-migration-check run --rm --no-deps --entrypoint "" web poetry run python manage.py migrate --noinput
docker compose -p jobapply-migration-check run --rm --no-deps --entrypoint "" web poetry run python manage.py check
docker compose -p jobapply-migration-check down -v
```

---

## Roadmap (next integration)

- Google Calendar integration (create interview events, reminders, sync)
- Django Paginator(fix list_applications qs = qs.order_by(sort)[:200])
- Email notifications
- Tech support form
- Mobile version

- Testing(pytest)
- Stronger backup/restore workflows (one-click restore)

**Author:** Maksym Petrykin  
Email: [m.petrykin@gmx.de](mailto:m.petrykin@gmx.de)  
Telegram: [@max_p95](https://t.me/max_p95)
