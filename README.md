# JobApply

[![CI](https://github.com/p95max/JobApply/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/JobApply/actions/workflows/ci.yml)

JobApply is a Django application for tracking job applications, recruiter replies and interviews. It uses a Google-first workflow: Google OAuth for authentication, read-only Gmail integration for response processing and optional Google Drive backups.

## Project status

**Gmail Assistant stage 1 is complete.** The production workflow has been verified against real Gmail messages and the relevant automated test suite passes with:

```text
139 passed, 0 failed
```

The completed checklist is maintained in [`TODO.md`](TODO.md).

## Main features

- Google-only authentication with `django-allauth`
- Application CRUD, statuses, filters and printable views
- Interview planner linked to applications
- Gmail statistics with read-only mailbox access
- AI-first Gmail Assistant with rule-based fallback
- Matching by Gmail thread, external application ID, company and job title
- Reviewable proposals: the Assistant never changes an application automatically
- Manual linking to an existing application or creation of a new application from an unmatched email
- Token usage dashboard with 7/30-day totals, daily chart, model breakdown and estimated cost
- Local PostgreSQL database with Google Drive dumps and optional Neon recovery sync
- Docker Compose development environment
- Native systemd/Caddy production deployment for a small VPS

## Stack

- Python 3.14
- Django 5.2
- PostgreSQL 18
- Bootstrap 5
- Poetry
- Pytest and Ruff
- OpenAI Responses API
- Google OAuth, Gmail API and Drive API

## Gmail Assistant

The Gmail Assistant imports relevant messages through the Gmail API using the read-only scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Workflow:

1. Sign in with Google.
2. Open **Services → Gmail Assistant**.
3. Enable AI analysis when required.
4. Run **Sync Gmail** or let the background worker check periodically.
5. Review the detected event, evidence, match and proposed changes.
6. Accept, edit, reject or ignore the proposal.
7. For unmatched messages, link an existing application or create a new one from extracted email data.

Only sanitized sender metadata, subject and bounded email text may be sent to OpenAI. Attachments are not sent. Gmail access remains read-only.

### Stage 1 capabilities

- bounded Gmail candidate queries instead of unrestricted mailbox processing
- inbound/outbound direction detection
- outgoing-message exclusion from Gmail statistics
- AI-first event classification with strict structured output
- rules fallback when AI is disabled, unavailable, over the daily limit or returns an error
- safe persistence of fallback error categories without provider details
- application matching by thread, external ID and normalized company/title
- normalization of gender markers such as `(m/w/d)`, `(f/m/d)` and `(gn)`
- reviewable application, interview and required-action proposals
- deterministic handling of known Indeed application-sent confirmations
- suppression of optional job-board outreach nudges
- periodic background sync and manual reanalysis
- explicit user approval before any application change

### AI configuration

```env
GMAIL_ASSISTANT_AI_ENABLED=1
GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=1
GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS=21600
GMAIL_ASSISTANT_AI_DAILY_LIMIT=50
GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD=80
GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED=1
OPENAI_API_KEY=...
OPENAI_EMAIL_MODEL=gpt-5.4-nano
```

AI is also controlled per user in the Gmail Assistant interface. The global environment flag alone does not opt a user in.

### Token usage and estimated cost

Every successful Gmail Assistant OpenAI request stores persistent usage telemetry in PostgreSQL:

- model name
- input tokens
- output tokens
- user and related Gmail message
- request timestamp

The **🪙 Token usage** subtab displays totals for 7 or 30 days, a daily chart and usage grouped by model. Cost is calculated per model, so historical requests made with an older model remain correctly represented.

For `gpt-5.4-nano`, the configured standard rates per one million tokens are:

```env
OPENAI_INPUT_USD_PER_1M=0.20
OPENAI_OUTPUT_USD_PER_1M=1.25
```

These generic environment values are used as fallback rates for unknown models. Known models use the model-specific price map in the application.

The displayed amount is an estimate rather than the OpenAI invoice total. Cached-input pricing is not separated. Requests completed before database usage tracking was introduced cannot be reconstructed exactly.

Migration:

```bash
python manage.py migrate
python manage.py showmigrations gmail_assistant
```

## Development with Docker Compose

### Requirements

- Docker
- Docker Compose v2
- Google Cloud OAuth credentials

Create `.env` from `.env.example` and configure at least:

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

POSTGRES_DB=jobapply
POSTGRES_USER=jobapply
POSTGRES_PASSWORD=jobapply
POSTGRES_HOST=db
POSTGRES_PORT=5432

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
DJANGO_SITE_DOMAIN=localhost:8000
DJANGO_SITE_NAME=JobApply

TURNSTILE_ENABLED=0
```

Start the project:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Run the Gmail worker logs:

```bash
docker compose logs -f gmail-assistant-worker
```

## Google Cloud setup

Enable these APIs in the Google Cloud project:

- Gmail API
- Google Drive API

For local development, register this OAuth callback:

```text
http://localhost:8000/accounts/google/login/callback/
```

For production, also register:

```text
https://jobapply.p95max.dev/accounts/google/login/callback/
```

The app uses these scopes:

```text
profile
email
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/drive.file
```

## Production VPS deployment

Production runs without Docker:

- Caddy terminates HTTPS and serves static/media files
- Gunicorn runs Django
- PostgreSQL is the local primary database
- `jobapply-gmail-worker.service` runs Gmail Assistant checks
- `jobapply-telegram-bot.service` runs Telegram notifications
- systemd timers run local backups and optional Neon synchronization

Deployment files are under:

```text
deploy/vps/
```

Important environment values:

```env
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=jobapply.p95max.dev,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://jobapply.p95max.dev
DJANGO_SITE_DOMAIN=jobapply.p95max.dev
ALLOWED_ACCOUNT_EMAILS=your-exact-google-email@example.com
```

`ALLOWED_ACCOUNT_EMAILS` is fail-closed. Set the exact Google account email before restarting the application.

### Standard production update

Check for local changes first:

```bash
cd /opt/jobapply
git status --short
```

Then update and validate:

```bash
sudo -u jobapply git pull --ff-only
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py migrate --noinput
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py check
sudo -u jobapply /opt/jobapply/.venv/bin/python manage.py collectstatic --noinput
systemctl restart jobapply-web
systemctl restart jobapply-gmail-worker
systemctl restart jobapply-telegram-bot
systemctl reload caddy
```

Check services:

```bash
systemctl status jobapply-web --no-pager -l
systemctl status jobapply-gmail-worker --no-pager -l
systemctl status jobapply-telegram-bot --no-pager -l
systemctl list-timers --all | grep jobapply
```

## Backups

The VPS profile supports:

- daily local PostgreSQL dumps
- upload to Google Drive through rclone
- weekly synchronization to an optional Neon recovery database

Relevant timers:

```text
jobapply-backup.timer
jobapply-neon-sync.timer
```

`active (waiting)` is the normal state for an enabled systemd timer.

## Testing

Run the complete quality gate:

```bash
poetry run pytest -ra -vv
poetry run ruff check .
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
```

The verified Gmail Assistant stage 1 test selection is:

```bash
DJANGO_SETTINGS_MODULE=config.settings poetry run pytest \
  tests/test_application_matcher.py \
  tests/test_gmail_assistant_pipeline.py \
  tests/test_gmail_assistant_views.py \
  tests/test_gmail_assistant_worker.py \
  tests/test_gmail_classifier.py \
  tests/test_gmail_credentials.py \
  tests/test_gmail_models.py \
  tests/test_gmail_sync.py \
  tests/test_message_parser.py \
  tests/test_proposals.py
```

Verified result on 4 August 2026:

```text
139 passed in 7.65s
```

With Docker:

```bash
docker compose exec web poetry run pytest -ra -vv
docker compose exec web poetry run ruff check .
docker compose exec web poetry run python manage.py check
docker compose exec web poetry run python manage.py makemigrations --check --dry-run
```

Verify migrations:

```bash
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py showmigrations gmail_assistant gmail_stats
```

## Translations

After changing user-facing text:

```bash
python manage.py makemessages -l de
python manage.py compilemessages
```

## Security and failure behavior

- Google OAuth is the only sign-in method.
- Gmail access is read-only.
- OpenAI requests use `store=False`.
- AI output is validated against a strict schema before use.
- Attachments are not sent to OpenAI.
- Proposals require explicit user review.
- Cross-user access to proposals and applications is blocked.
- API and mailbox errors are isolated to the affected sync/message.
- Rules fallback preserves a safe error category without exposing provider details.
- Token usage persistence is telemetry and does not control analysis success.
- Secrets belong in `.env` and must never be committed.

## Author

Maksym Petrykin
