# JobApply

[![CI](https://github.com/p95max/JobApply/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/JobApply/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/p95max/JobApply/branch/master/graph/badge.svg)](https://codecov.io/gh/p95max/JobApply)

JobApply is a Django application for managing job applications, interviews and recruiter replies. Users sign in with Google, can connect Gmail for read-only analysis, and may store personal CSV backups in their own Google Drive.

The Gmail Assistant is deliberately review-first: it analyses emails and prepares proposals; meaningful changes are reviewed by the user before they affect an application. A narrow opt-in auto-apply mode is available only for trusted, low-risk updates.

## What it provides

- Google OAuth sign-in with a demo-friendly public landing page
- Job application tracking: statuses, notes, filters, imports/exports and printable views
- Interview planning linked to applications
- Gmail statistics and a Gmail Assistant for recruiter replies and sent applications
- Rule-based classification with optional OpenAI analysis and per-user daily limits
- Matching by Gmail thread, application reference, sender/domain, company and normalized role
- Guided five-step proposal review with evidence, edit fields, optional notes and safe linking
- Telegram notifications and a private user/administrator bot menu
- Personal Google Drive CSV backups, manual or automated
- Docker Compose development and a systemd/Caddy/Gunicorn VPS deployment

## Stack

- Python 3.13+
- Django 5.2
- PostgreSQL
- Bootstrap 5
- Poetry, Pytest and Ruff
- Google OAuth, Gmail API and Google Drive API
- OpenAI Responses API (optional)
- Telegram Bot API (optional)

## Demo mode

The public landing page can create an isolated temporary demo workspace without Google OAuth. Demo accounts are marked with `UserProfile.is_demo_user=True`, use the normal application UI with connected-service restrictions, and are intentionally short-lived.

The default demo lifetime is **12 hours**. Demo creation is protected by a per-IP cooldown and daily allowance, so a public portfolio page cannot be used to create unlimited accounts:

```env
DEMO_ACCOUNT_TTL_HOURS=12
DEMO_START_MAX_PER_IP_PER_DAY=3
DEMO_START_COOLDOWN_SECONDS=60
# Enable only when the reverse proxy overwrites X-Forwarded-For.
DEMO_START_TRUST_X_FORWARDED_FOR=0
```

The demo session expiry is aligned with the same TTL. Expired demo users are deleted by the `cleanup_demo_users` management command together with related data through Django cascading deletes. On the VPS, `jobapply-demo-cleanup.timer` runs the cleanup regularly, so stale demo workspaces do not accumulate.

Manual checks:

```bash
python manage.py cleanup_demo_users --dry-run
python manage.py cleanup_demo_users
```

When a visitor enters demo mode from the landing page, the configured Telegram administrator receives a `Demo mode started` notification. The owner-only `/newusers` command reports registered users from the last seven days and shows demo workspaces as a separate count rather than mixing anonymous demos into the email list.

## Gmail Assistant

Gmail access uses the read-only OAuth scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

The Assistant recognises, among other things:

- application sent or received
- confirmations and actions required
- requests for documents
- recruiter replies, rejections, interviews, offers and cancellations
- applications sent manually from the user's own Gmail account

It reads inbound mail and can also import relevant messages from **Sent**. Sent messages are labelled `myself_sent`; the user's own email address is never interpreted as an employer.

### User workflow

1. Sign in with Google and open **Gmail Assistant**.
2. Optionally enable AI analysis for the current account.
3. Pick a sync period (one day, week, month, three months or six months) and press **Sync Gmail**.
4. Filter or search pending suggestions and open a card.
5. Review the source email, evidence, detected values and matching result.
6. Link an existing application when appropriate, edit extracted values if required, then accept, reject or ignore.

For a rejection received before any known confirmation, the review page offers **Create rejected application**. This is an explicit manual action and uses the information visible in that email; it does not invent a previous confirmation.

Cards make the analysis source visible:

- `🤖 AI` means OpenAI produced the final structured classification.
- `⚙️` means deterministic rules were used.
- Every card displays its confidence and matching result.

### Matching and safety

Matching is deterministic before fuzzy matching is considered. It prioritises Gmail thread history, application/job IDs, verified sender domain, normalized company and title, and only then fallback similarity. During a full resync, pending `create_application` suggestions can temporarily act as targets for follow-up emails, so a rejection or interview can be linked before its application is accepted. Known job platforms such as Stepstone and Indeed are not treated as employers when better company data is available.

An unmatched proposal never updates an arbitrary application. Rejections, interviews, offers and requested actions remain pending until the user links and accepts them. New applications can be created only after review or through the dedicated bulk action below.

### AI analysis and limits

Only sanitised sender metadata, subject and bounded plain-text email content may be sent to OpenAI. Attachments are never sent. Requests use `store=False`.

AI is an opt-in setting for each user. The global configuration only enables the capability; it does not grant consent for any account. The default limit is **50 emails per user per day**. The same Gmail message is not repeatedly charged: already analysed messages are reused unless a deliberate reanalysis is requested.

The Assistant can automatically check opted-in accounts. The interval comes from `GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS`; it is 15 minutes in the example configuration. Syncing a larger period may take from seconds to a few minutes.

Each user can have only one Gmail sync at a time. A simultaneous manual or scheduled attempt is safely skipped, rather than processing the same mailbox twice. Manual requests also have a short per-user cooldown before any Google API calls are made.

`Automatically accept trusted updates` is deliberately restrictive. It applies only low-risk status changes with a verified exact application match and confidence at or above the configured threshold. Rejections, offers, interviews, actions, newly created applications and uncertain matches always remain pending.

The **Create high-confidence applications** action is separate. It creates only unmatched new-application suggestions with AI confidence of at least 75%; it never processes rejections, interviews or actions. Review the resulting applications for duplicates.

Relevant settings:

```env
GMAIL_ASSISTANT_AI_ENABLED=0
GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=1
GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS=900
GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS=60
GMAIL_SYNC_LOCK_TIMEOUT_SECONDS=1800
GMAIL_ASSISTANT_AI_DAILY_LIMIT=50
GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD=80
GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED=1
# A rejection can be linked to one active application at the same company
# when its application date is within this lookback period.
GMAIL_REJECTION_MATCH_LOOKBACK_DAYS=90
OPENAI_API_KEY=...
OPENAI_EMAIL_MODEL=gpt-5.4-nano
```

Development reset and reanalysis tools are shown only when both conditions apply:

```env
GMAIL_ASSISTANT_DEV_TOOLS=1
TELEGRAM_OWNER_EMAIL=owner@example.com
```

The signed-in email must equal `TELEGRAM_OWNER_EMAIL`. These tools reset only that account's Gmail Assistant data or daily AI counter; they do not remove the Google connection.

### Token usage

The Token usage page records successful OpenAI requests per user and message: model, input/output tokens and timestamp. It provides 7/30-day totals, daily history, model breakdown and an estimated cost. The amount is an estimate, not an invoice total.

## Google OAuth and APIs

Enable **Gmail API** and **Google Drive API** in the Google Cloud project. JobApply asks for:

```text
openid
email
profile
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/drive.file
```

`drive.file` allows only files created by JobApply. It does not grant access to every file in a user's Drive.

Register the correct callback for each environment:

```text
http://localhost:8000/accounts/google/login/callback/
https://your-domain.example/accounts/google/login/callback/
```

For a Codespaces public port, use its public HTTPS domain in `DJANGO_SITE_DOMAIN`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and the Google callback. Do not use `0.0.0.0:8000` as an external OAuth callback.

## Personal Google Drive backups

In **Services → Cloud backups**, a connected user can:

- save an application CSV backup manually with **Save backup manually**;
- restore a saved CSV backup;
- enable personal automatic backups.

Automatic personal backups retain the latest three CSV files in that user's JobApply Drive folder. The worker checks enabled accounts every five minutes but uploads only when the configured interval is due; the default is six hours:

```env
PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS=21600
```

The personal backup worker must run in every environment. In Docker Compose it is `backup-worker`; on a VPS it is `jobapply-drive-backup-worker.service`.

VPS database dumps and optional Neon recovery synchronisation are separate server operations, not copies of a user's personal applications. Their schedule is displayed only to the configured operations owner.

## Telegram bot

Telegram is optional. Linking a bot from **Services → Telegram** can use the normal Telegram redirect or a one-time code entered in the bot.

The bot uses command scopes, so ordinary private chats see only:

- `/help`
- `/ping`
- `/gmail`
- `/applications`

`/gmail` opens the Gmail Assistant review page and `/applications` provides a compact application summary with a hidden link to JobApply. It does not expose infrastructure data or mass action buttons.

The configured owner additionally sees:

- `/admin`
- `/status`
- `/newusers`
- `/health`
- `/doctor`
- `/deploy`

`/newusers` shows active registered users from the last seven days by email and date, plus a separate `Demo workspaces` count for demo-mode sessions created during the same period.

Administrative commands require both the configured owner user ID and private chat ID. The bot rate-limits inbound updates and `/ping` gives a user-visible liveness response. Telegram failures are isolated from Gmail and application processing. A systemd failure hook can alert the owner if the bot service fails.

```env
TELEGRAM_BOT_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...
TELEGRAM_ALLOWED_CHAT_IDS=...
TELEGRAM_ALLOWED_USER_IDS=...
TELEGRAM_OWNER_USER_ID=...
TELEGRAM_OWNER_EMAIL=owner@example.com
TELEGRAM_NOTIFICATIONS_ENABLED=1
TELEGRAM_CALLBACK_TTL_SECONDS=900
TELEGRAM_RATE_LIMIT_COUNT=20
TELEGRAM_RATE_LIMIT_WINDOW_SECONDS=60
TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS=60
```

Never commit a Telegram token or real account/chat IDs.

## Abuse controls and resource limits

Expensive or destructive operations are bounded per user before work starts. The database reservation used for CSV imports and Drive operations is atomic, so concurrent requests cannot bypass the daily limit. Gmail syncs use a separate per-user lock.

```env
# Application records and bulk deletion
APPLICATIONS_PER_USER_LIMIT=1000
APPLICATION_BULK_DELETE_MAX_IDS=200

# CSV imports per user
CSV_IMPORT_DAILY_LIMIT=3
CSV_IMPORT_COOLDOWN_SECONDS=60

# Manual Google Drive save/restore operations per user
DRIVE_MANUAL_OPERATION_DAILY_LIMIT=20
DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS=30
```

The Google OAuth entry point is protected by Turnstile for anonymous visitors when enabled. Do not add broad URL exemptions for `/accounts/google/`: the verification gate must remain in front of the OAuth redirect.

## Development with Docker Compose

### Requirements

- Docker and Docker Compose v2
- Google OAuth credentials

Create `.env` from `.env.example`, then configure at least:

```env
DJANGO_SECRET_KEY=change-me
OAUTH_TOKEN_ENCRYPTION_KEY=...
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
TURNSTILE_ENABLED=0
```

Start all development services:

```bash
docker compose up --build
```

Open <http://localhost:8000>. The Compose profile includes PostgreSQL, the web service, Gmail Assistant worker and personal Drive backup worker.

Useful logs:

```bash
docker compose logs -f gmail-assistant-worker
docker compose logs -f backup-worker
```

## Production VPS deployment

Production is designed for Caddy, Gunicorn, local PostgreSQL and systemd. The detailed bootstrap guide is [deploy/vps/README.md](deploy/vps/README.md).

Core services:

- `jobapply-web.service` — Gunicorn/Django
- `jobapply-gmail-worker.service` — automatic Gmail Assistant sync
- `jobapply-drive-backup-worker.service` — personal Drive backup loop
- `jobapply-telegram-bot.service` — optional Telegram polling
- `jobapply-demo-cleanup.timer` — periodic deletion of expired demo workspaces
- `jobapply-backup.timer` — server PostgreSQL dump and off-site upload
- `jobapply-neon-sync.timer` — optional recovery-database sync

After deploying a version containing new operations files, install/update the units once as root:

```bash
cd /opt/jobapply
sudo bash deploy/vps/install-ops.sh
```

The script is intentionally invoked through `bash`; it is not required to have an executable bit. It installs systemd units, scripts, Caddy configuration, journal retention and the shared job lock permissions.

Check the personal backup worker:

```bash
sudo systemctl status jobapply-drive-backup-worker.service --no-pager -l
sudo journalctl -u jobapply-drive-backup-worker.service -n 80 --no-pager -l
```

Check demo cleanup:

```bash
sudo systemctl status jobapply-demo-cleanup.timer --no-pager -l
systemctl list-timers --all | grep jobapply-demo-cleanup
```

Minimum production configuration:

```env
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=your-domain.example,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example
DJANGO_SITE_DOMAIN=your-domain.example
DJANGO_USE_X_FORWARDED_HOST=1
DJANGO_SECURE_PROXY_SSL_HEADER=1
OAUTH_TOKEN_ENCRYPTION_KEY=replace-with-a-separate-long-random-value
TURNSTILE_ENABLED=1
TURNSTILE_SITE_KEY=...
TURNSTILE_SECRET_KEY=...
DEMO_ACCOUNT_TTL_HOURS=12
# Leave empty to allow any Google account. To restrict access, provide a comma-separated list.
ALLOWED_ACCOUNT_EMAILS=
# Keep the admin URL non-obvious. Optionally restrict it to known IP addresses.
ADMIN_URL=backoffice
ADMIN_ALLOWED_IPS=
# Enable only when Caddy overwrites X-Forwarded-For.
ADMIN_TRUST_X_FORWARDED_FOR=0
```

`ALLOWED_ACCOUNT_EMAILS` is optional. When empty, any Google account may sign in. When set, only the comma-separated listed accounts may sign in.

### Safe deploys

Production deploys only from `master`. The fixed deploy script rejects a dirty working tree, another branch and non-fast-forward history. It installs locked dependencies, runs the test suite and Django checks, applies migrations, collects static files, restarts known services and runs a health check.

The owner-only Telegram `/deploy` flow has a one-time confirmation and cannot accept a branch or shell arguments. It can start only the fixed `jobapply-deploy.service` through the installed minimal sudoers rule.

Manual emergency deploy:

```bash
sudo /usr/local/sbin/jobapply-deploy
```

Inspect a deployment:

```bash
sudo journalctl -u jobapply-deploy.service -n 100 --no-pager -l
sudo tail -n 180 /var/log/jobapply/deploy-last.log
```

### Staff AI audit API

The read-only OpenAPI (Swagger-compatible) audit API is disabled by default. To enable it for staff users only, generate an unguessable path segment and add it to the production `.env`:

```bash
python3 -c 'import secrets; print(f"AI_AUDIT_URL=ai-audit-{secrets.token_urlsafe(24)}")'
```

After restarting the web service, open `https://your-domain.example/<AI_AUDIT_URL>/`. The page opens each JSON resource in a separate browser tab and links to the OpenAPI schema. Available read-only datasets are all applications, applications with pending proposals, high-confidence pending creates, AI proposals, Gmail analyses and the AI history for a selected application. They expose only processing metadata and linked application fields; they never return Gmail subjects, bodies, OAuth credentials or private review notes. The endpoint returns `404` for anonymous users, non-staff users and incorrect URLs.

## Legal pages and privacy

Before publishing a public demo, complete the legal values in the environment:

```env
LEGAL_PROVIDER_NAME=...
LEGAL_PROVIDER_ADDRESS=...
LEGAL_CONTACT_EMAIL=...
LEGAL_PRIVACY_CONTACT_EMAIL=...
LEGAL_SUPERVISORY_AUTHORITY=...
LEGAL_LOG_RETENTION=14 Tage
```

JobApply includes localized **Impressum**, privacy policy and terms pages, a functional cookie-consent dialog and account deletion from profile settings with a confirmation alert. The privacy policy documents Gmail and optional Google Drive access. Obtain qualified legal advice for the final information and jurisdiction-specific requirements.

## Testing

Run the quality gate in the same environment that will run the application:

```bash
poetry run pytest -ra -vv
poetry run ruff check .
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry check --lock
```

With Docker:

```bash
docker compose exec web poetry run pytest -ra -vv
docker compose exec web poetry run ruff check .
docker compose exec web poetry run python manage.py check
docker compose exec web poetry run python manage.py makemigrations --check --dry-run
```

On the VPS, use the deployment test command or the project virtualenv under the `jobapply` system user. The deploy process temporarily grants the database role only the `CREATEDB` permission required by Django test database creation, then revokes it again.

After changing translatable UI text:

```bash
python manage.py makemessages -l de
python manage.py compilemessages
```

## Security model

- Google OAuth is the standard sign-in path; demo workspaces are isolated, temporary and rate-limited.
- Gmail permission is read-only; Drive uses the narrow `drive.file` scope.
- OAuth access and refresh tokens are encrypted at rest, using `OAUTH_TOKEN_ENCRYPTION_KEY` when configured (otherwise the required Django secret key).
- Attachments are never sent to AI; requests use `store=False`.
- AI output is validated against a strict structured schema.
- Cross-user access to applications, Gmail proposals and Drive backups is blocked.
- Gmail syncs are serialized per account; AI quotas and operation limits are reserved atomically.
- Admin sign-in is throttled and can be restricted to explicit IP addresses.
- Gmail/AI/provider failures are isolated to a message or user and do not roll back existing data.
- Telegram command access requires configured private user and chat allowlists.
- Deployment is fixed to `master`, confirmation-gated and rejects local changes.
- Secrets belong in `.env`, never in Git, logs or screenshots.

## Author

Maksym Petrykin
