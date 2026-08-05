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

Production deploys only from `master`.

Check the branch and local changes first:

```bash
cd /opt/jobapply
git branch --show-current
git status --short
```

Then update and validate:

```bash
sudo -u jobapply git -C /opt/jobapply pull --ff-only origin master
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

## Telegram Bot

The Telegram Bot is a private owner dashboard. It does not accept arbitrary shell commands. Gmail proposals remain review-first: each Accept or Reject action is explicit and is checked again against the current proposal state.

The native Telegram menu uses two command scopes. All private chats receive only application-facing commands:

- `/help`
- `/gmail`
- `/applications`

The configured owner chat receives those commands plus the administrative menu:

- `/admin`
- `/status`
- `/health`
- `/doctor`
- `/deploy`

`/help` is role-aware and does not expose administrative commands to a client chat. `/admin`, `/status`, `/health`, `/doctor` and `/deploy` require both the configured owner user ID and the configured owner chat ID. `/gmail` provides **Open**, **Accept** and **Reject** buttons for pending proposals; the bot rechecks the user, chat, expiry and proposal status before an action is applied. `/health` reports database, disk and worker heartbeats; `/doctor` additionally reports the branch, working tree, migrations and known systemd units.

### BotFather setup

1. Create a bot with `@BotFather` using `/newbot`.
2. Store the returned token only in `/opt/jobapply/.env`.
3. Send a private message to the bot.
4. Read the update through the Bot API to obtain the private `from.id` and `chat.id` values.
5. Configure the command list in BotFather or let `run_telegram_bot` publish it at startup.

Never commit the bot token or real Telegram IDs.

### Production configuration

```env
TELEGRAM_BOT_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...
TELEGRAM_ALLOWED_CHAT_IDS=...
TELEGRAM_ALLOWED_USER_IDS=...
TELEGRAM_OWNER_EMAIL=your-exact-google-email@example.com
TELEGRAM_ENV_LABEL=PRODUCTION
TELEGRAM_NOTIFICATIONS_ENABLED=1
# Keep production deploy disabled until the systemd unit and sudoers rule are verified.
TELEGRAM_DEPLOY_ENABLED=0
TELEGRAM_DEPLOY_CONFIRMATION_TTL_SECONDS=300
JOBAPPLY_PRODUCTION_BRANCH=master
```

The bot validates the token and allowlists before polling. Both `from_user.id` and private `chat.id` must match the configured allowlists.

### Owner-only deploy

`/deploy` accepts no branch name or shell arguments. It displays the current and target `master` commits and requires a short-lived, one-time **Confirm deploy** callback. The bot can invoke only `jobapply-deploy.service` through this minimal sudoers rule:

```text
jobapply ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block start jobapply-deploy.service
```

The fixed deploy script refuses a non-`master` branch, local changes and non-fast-forward updates. It then runs tests, Django checks, migrations, static collection, known JobApply service restarts and an HTTP health check. Manual emergency deployment uses the same fixed script:

```bash
sudo /usr/local/sbin/jobapply-deploy
```

Inspect a deploy with:

```bash
sudo journalctl -u jobapply-deploy.service -n 100 --no-pager -l
```

### systemd service

The production unit is `jobapply-telegram-bot.service`. It runs as `jobapply`, uses `/opt/jobapply` as its working directory and loads `/opt/jobapply/.env`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jobapply-telegram-bot.service
sudo systemctl restart jobapply-telegram-bot.service
sudo systemctl status jobapply-telegram-bot.service --no-pager -l
```

Logs:

```bash
sudo journalctl -u jobapply-telegram-bot.service -n 100 --no-pager -l
sudo journalctl -u jobapply-telegram-bot.service -f
```

### Disable the bot

Set:

```env
TELEGRAM_BOT_ENABLED=0
TELEGRAM_NOTIFICATIONS_ENABLED=0
```

Then stop and disable the polling service:

```bash
sudo systemctl disable --now jobapply-telegram-bot.service
```

The web application, Gmail worker and backup service continue operating without Telegram.

### Rotate the Telegram token

1. Revoke or regenerate the token in `@BotFather`.
2. Replace only `TELEGRAM_BOT_TOKEN` in `/opt/jobapply/.env`.
3. Restart the bot service.
4. Verify `/status` and review the service logs.

```bash
sudo systemctl restart jobapply-telegram-bot.service
sudo systemctl status jobapply-telegram-bot.service --no-pager -l
```

Do not print the token in shell history, logs, screenshots or support messages.

### VPS smoke checks

Run these after changing Telegram configuration or deploying a new version:

```bash
sudo systemctl is-active jobapply-web.service jobapply-gmail-worker.service jobapply-telegram-bot.service
sudo systemctl status jobapply-telegram-bot.service --no-pager -l
pgrep -af 'manage.py run_telegram_bot'
sudo journalctl -u jobapply-telegram-bot.service -n 100 --no-pager -l
```

There must be one polling process. In Telegram, verify `/status`, `/gmail`, `/applications`, `/health` and owner-only `/doctor`. To verify isolation, stop the bot briefly and confirm that the web and Gmail worker services remain active:

```bash
sudo systemctl stop jobapply-telegram-bot.service
sudo systemctl is-active jobapply-web.service jobapply-gmail-worker.service
sudo systemctl start jobapply-telegram-bot.service
```

After a planned reboot, repeat the commands above and verify that the bot responds to `/status`. Do not test access with an untrusted Telegram account that has been added to an allowlist.

### Notifications

The first version sends only significant events:

- rejection proposal
- interview invitation proposal
- Gmail OAuth reconnect required
- Gmail synchronization failure
- backup failure

Notifications use persistent delivery records, unique event keys, bounded retries and safe error categories. Delivery errors do not roll back Gmail proposals, heartbeat updates or backup operations.

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
- Telegram access is restricted to configured private user and chat IDs.
- Telegram delivery failures do not roll back business operations.
- Secrets belong in `.env` and must never be committed.

## Author

Maksym Petrykin
