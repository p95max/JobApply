# JobApply

[![CI](https://github.com/p95max/JobApply/actions/workflows/ci.yml/badge.svg)](https://github.com/p95max/JobApply/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/p95max/JobApply/branch/master/graph/badge.svg)](https://codecov.io/gh/p95max/JobApply)

JobApply is a Django application for tracking job applications and interviews and for turning Gmail recruiting traffic into auditable application updates.

Users sign in with Google, manage applications in the web UI, optionally connect Gmail for read-only analysis, and can save personal CSV backups to their own Google Drive. The Gmail Assistant combines deterministic rules, optional OpenAI analysis, application matching, explicit proposal review, trusted auto-apply, token accounting and Telegram notifications.

The core design is **review-first and provenance-aware**: an email is analysed first, then represented as a proposal or recorded Gmail activity. Application state is changed only by an accepted action or by the deliberately narrow trusted auto-apply path. Sent applications keep their Gmail provenance and do not masquerade as recruiter replies.

## Current feature set

- Google OAuth sign-in and a rate-limited temporary demo mode
- Application tracker with statuses, notes, filters, CSV import/export and printable views
- Interview records linked to applications
- Gmail statistics plus Gmail Assistant analysis for Inbox and manually selected Sent mail
- Rule-based classification with optional OpenAI structured analysis
- Per-user atomic daily AI-call quota and persistent input/output token accounting
- Deterministic-first application matching using thread history, references, sender/domain, company and normalized role
- Proposal workflow for create/update application, create/update interview and action-required events
- Canonical Action history with Gmail provenance, search and pagination
- Recovery of a deleted application from the already accepted Sent-Gmail history without fabricating a recruiter event
- Narrow trusted auto-apply for low-risk exact matches
- Telegram user/admin bot, Gmail summaries, system alerts and AI quota exhaustion alerts
- Staff AI audit API behind an optional unguessable path
- Personal Google Drive CSV backups, manual or automatic
- Local Docker Compose setup and production Caddy + Gunicorn + systemd deployment

## Stack

- Python 3.13+
- Django 5.2
- PostgreSQL 18 in Docker development
- Bootstrap 5
- Poetry
- Pytest / pytest-django
- Ruff
- django-allauth
- Google OAuth, Gmail API and Google Drive API
- OpenAI Responses API (optional)
- Telegram Bot API (optional)

## Project structure

The current Django codebase is split into focused apps:

```text
apps/
├── accounts/         Google login, profiles, demo users and connected services
├── applications/     application tracker, imports/exports and application views
├── interviews/       interview records and application linkage
├── gmail_stats/      Gmail sync, stored messages, credentials and statistics
├── gmail_assistant/  classification, AI, matching, proposals, history and token usage
├── telegram_bot/     bot commands, notifications, health/deploy integration
├── reports/          reporting and AI/token statistics
├── security/         security controls and protected entry points
└── legal/            Impressum, privacy and terms pages
```

Operational files live under `deploy/vps/`; Docker development uses `docker-compose.yml` and `docker/web/Dockerfile`.

## Demo mode

The public landing page can create an isolated temporary demo workspace without Google OAuth. Demo accounts use the normal application UI with connected-service restrictions and are intentionally short-lived.

The default lifetime is **12 hours**. Creation is rate-limited per IP:

```env
DEMO_ACCOUNT_TTL_HOURS=12
DEMO_START_MAX_PER_IP_PER_DAY=3
DEMO_START_COOLDOWN_SECONDS=60
DEMO_START_TRUST_X_FORWARDED_FOR=0
```

Expired workspaces are deleted by `cleanup_demo_users`. Production runs the cleanup from `jobapply-demo-cleanup.timer`.

```bash
python manage.py cleanup_demo_users --dry-run
python manage.py cleanup_demo_users
```

Starting a demo can notify the configured Telegram administrator. `/newusers` keeps temporary demo workspaces separate from normal registered-user counts.

## Gmail Assistant

Gmail is accessed with the read-only scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

The Assistant recognises events including:

- application sent / application received
- application confirmation
- recruiter/general update
- action required / documents requested
- rejection
- interview invitation, reschedule and cancellation
- offer
- manually sent direct applications from the user's Gmail Sent mailbox

Inbound mail is processed by normal sync. Sent scanning is manual: the user explicitly enables **Include applications sent by me** for a sync/reanalysis operation. Automatic background checks do not scan Sent.

### Analysis pipeline

At a high level:

```text
Gmail API
  -> GmailMessage
  -> deterministic rules
  -> optional OpenAI structured classification
  -> GmailAnalysis
  -> application matching
  -> ApplicationUpdateProposal / accepted Gmail activity
  -> review or trusted auto-apply
  -> JobApplication / Interview
```

Rules are used as the first line of classification and as the configured fallback. AI requests use sanitized bounded email text and structured output. Attachments are never sent to the AI provider.

### User workflow

1. Sign in with Google and open **Gmail Assistant**.
2. Enable AI analysis if desired.
3. Select a Gmail sync period.
4. Optionally include relevant applications from Sent.
5. Review pending suggestions and their source email, confidence and matching evidence.
6. Link or edit the target when necessary.
7. Accept, reject or ignore the proposal.
8. Review completed actions in **Action history**.

Pending suggestions support search/filtering. Action history is server-searchable by Gmail subject/sender and linked application company/role and is paginated independently from pending suggestions.

The FAQ on the Gmail Assistant page is collapsed by default; individual FAQ questions remain independently expandable.

### Action history and provenance

Action history records the **action that actually happened**, not just the classifier event that triggered it.

Examples:

- an outbound direct application that created a tracker entry is shown as `Create application`;
- a rejection that changed an existing application is shown as `Update application`;
- a processed Gmail event that required no create/update action can be represented as `Gmail activity`.

The Gmail event remains the provenance source. This prevents an outbound application from being presented as an HR reply.

For direct applications imported from Sent, JobApply preserves the original Gmail timestamp and marks the application as sent by the user. If that application is later deleted while its accepted Gmail history still exists, a subsequent successful Gmail processing cycle can reconstruct a pending create operation from the stale accepted record. Once recreated and accepted, obsolete orphaned duplicates are superseded so Action history contains one canonical accepted event.

The application detail/list UI derives activity dates from semantic Gmail/application events rather than treating a later database update timestamp as a recruiter interaction.

### Matching and safety

Matching is deterministic before fuzzy similarity is considered. Important signals include:

- Gmail thread history
- application/job/reference IDs
- verified sender/domain
- normalized employer name
- normalized role/title
- controlled fallback similarity

Known job platforms such as Indeed and Stepstone are not treated as the employer when better company evidence exists.

An unmatched proposal never updates an arbitrary application. Rejections, interviews, offers and requested actions stay pending until a safe link exists or the user resolves the match.

`Automatically accept trusted updates` is intentionally narrow: only low-risk updates with a verified exact application match and sufficiently high confidence are eligible. Rejections, offers, interviews, action-required items, newly created applications and uncertain matches remain reviewable.

The separate **Create high-confidence applications** operation can create unmatched new-application suggestions above its confidence threshold; it does not bulk-accept rejections/interviews/actions.

### AI quota and token usage

AI is opt-in per user. The app-level default is **50 potentially billable AI calls per user per day**.

The reservation is atomic: concurrent workers cannot consume more than the configured daily limit. Reusing an already analysed Gmail message does not consume another reservation unless deliberate reanalysis is requested.

Successful OpenAI responses are persisted in `OpenAITokenUsage` with:

- user
- Gmail message
- model name
- input tokens
- output tokens
- timestamp

The reporting UI provides request/token totals, daily history, model breakdown and estimated cost. Cost is an estimate, not an OpenAI invoice balance.

JobApply does **not** know the remaining OpenAI account balance. It knows the remaining internal daily AI-call quota and the tokens already consumed by recorded successful requests.

The Gmail background worker includes both in Telegram summaries, for example:

```text
⚡ AI quota left: 37/50 calls
🪙 OpenAI tokens used today: 12,450
```

When the last available app-level call is reserved, Telegram sends a deduplicated daily critical notification:

```text
🚨 AI quota exhausted
⚡ AI calls left: 0/50
```

Further AI analysis is blocked until the app-level daily quota resets. Rule fallback can continue where the processing path permits it.

Relevant configuration:

```env
GMAIL_ASSISTANT_AI_ENABLED=0
GMAIL_ASSISTANT_AUTO_SYNC_ENABLED=1
GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS=900
GMAIL_ASSISTANT_AI_DAILY_LIMIT=50
GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD=80
GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED=1
GMAIL_REJECTION_MATCH_LOOKBACK_DAYS=90
OPENAI_API_KEY=...
OPENAI_EMAIL_MODEL=gpt-5.4-nano
```

Development reset/reanalysis controls are visible only for the configured owner account when dev tools are enabled:

```env
GMAIL_ASSISTANT_DEV_TOOLS=1
TELEGRAM_OWNER_EMAIL=owner@example.com
```

They reset only the current owner's Gmail Assistant data or daily AI counter; they do not remove the Google connection.

## Google OAuth and APIs

Enable Gmail API and Google Drive API in the Google Cloud project. JobApply requests:

```text
openid
email
profile
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/drive.file
```

`drive.file` limits Drive access to files created/opened through JobApply rather than granting blanket access to the user's Drive.

Register the correct callback for each environment:

```text
http://localhost:8000/accounts/google/login/callback/
https://your-domain.example/accounts/google/login/callback/
```

For a public Codespaces port, use its HTTPS host in `DJANGO_SITE_DOMAIN`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and the Google OAuth callback.

OAuth access/refresh tokens are encrypted at rest. Configure a stable secret separate from the Django secret when possible:

```env
OAUTH_TOKEN_ENCRYPTION_KEY=...
```

## Personal Google Drive backups

In **Services → Cloud backups**, a connected user can:

- save an application CSV backup manually;
- restore a saved CSV backup;
- enable personal automatic backups.

Automatic personal backups retain the latest three application CSV files created by JobApply. The default backup interval is six hours:

```env
PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS=21600
```

Docker service: `backup-worker`.

Production service: `jobapply-drive-backup-worker.service`.

Server PostgreSQL dumps and optional Neon recovery sync are separate operational backups and are not the user's personal Drive backup feature.

## Telegram bot

Telegram is optional and linked from **Services → Telegram**. A user can connect through the normal Telegram flow or a short-lived link code.

Normal private-chat commands include:

- `/help`
- `/ping`
- `/gmail`
- `/applications`

The configured owner additionally has administrative commands including:

- `/admin`
- `/status`
- `/newusers`
- `/health`
- `/doctor`
- `/deploy`

The bot and notification layer also handle operational events such as:

- Gmail Assistant summaries
- Gmail OAuth/sync errors
- relevant proposal notifications
- demo-mode starts
- service/deployment alerts
- app-level AI quota exhaustion

User-facing Gmail/application links are rendered as Telegram inline buttons where supported instead of exposing raw URLs in notification text.

Administrative commands require the configured owner identity/private chat. Bot failures are isolated from Gmail/application writes. Notifications use deduplication keys where repeated delivery would otherwise cause alert spam.

Core configuration:

```env
TELEGRAM_BOT_ENABLED=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...
TELEGRAM_ALLOWED_CHAT_IDS=...
TELEGRAM_ALLOWED_USER_IDS=...
TELEGRAM_OWNER_USER_ID=...
TELEGRAM_OWNER_EMAIL=owner@example.com
TELEGRAM_ENV_LABEL=PRODUCTION
TELEGRAM_NOTIFICATIONS_ENABLED=1
TELEGRAM_CALLBACK_TTL_SECONDS=900
TELEGRAM_RATE_LIMIT_COUNT=20
TELEGRAM_RATE_LIMIT_WINDOW_SECONDS=60
TELEGRAM_DEPLOY_ENABLED=0
TELEGRAM_DEPLOY_CONFIRMATION_TTL_SECONDS=300
JOBAPPLY_PRODUCTION_BRANCH=master
```

Never commit a real Telegram token, private account IDs or chat IDs.

## Reports and staff administration

The reports layer exposes application statistics and AI/token usage. Token reporting is based on persisted `OpenAITokenUsage`, not estimates inferred from email counts.

The Django administration area can be deployed behind a non-obvious path and optional IP restriction. Administrative user views are intended for active account oversight and AI usage visibility; they are separate from ordinary user-facing reports.

```env
ADMIN_URL=backoffice
ADMIN_ALLOWED_IPS=
ADMIN_TRUST_X_FORWARDED_FOR=0
```

### Staff AI audit API

A read-only OpenAPI/Swagger-compatible audit surface exists for staff diagnostics and is disabled by default.

```env
AI_AUDIT_URL=
AI_AUDIT_API_MAX_PAGE_SIZE=100
```

For production, configure an unguessable single path segment. The API exposes processing/application metadata needed for AI-assistant diagnostics while intentionally excluding Gmail bodies, OAuth credentials and other secrets. Incorrect paths and unauthorized users receive `404`.

## Abuse controls and security boundaries

Expensive/destructive operations are bounded before work starts. Gmail sync uses a per-user lock; AI reservations and other resource limits use atomic database state where appropriate.

Important boundaries include:

- Gmail scope is read-only.
- Google Drive uses `drive.file`.
- OAuth tokens are encrypted at rest.
- AI receives sanitized bounded email text; attachments are never sent.
- OpenAI requests use `store=False` in the Gmail analysis path.
- AI output is validated as structured data before it is used.
- Cross-user application, Gmail proposal and backup access is blocked.
- Unmatched Gmail events do not mutate arbitrary applications.
- User AI quotas are atomically reserved.
- Telegram owner commands use explicit user/chat allowlists.
- Turnstile can protect anonymous OAuth/demo entry points.
- Admin access can use a custom URL and IP restriction.
- Production deployment is fixed to `master` and rejects a dirty/non-fast-forward checkout.

Example application/operation limits supported by the deployment configuration include:

```env
APPLICATIONS_PER_USER_LIMIT=1000
APPLICATION_BULK_DELETE_MAX_IDS=200
CSV_IMPORT_DAILY_LIMIT=3
CSV_IMPORT_COOLDOWN_SECONDS=60
DRIVE_MANUAL_OPERATION_DAILY_LIMIT=20
DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS=30
```

## Legal pages and privacy

JobApply includes localized:

- Impressum
- privacy policy
- terms of use
- cookie-consent UI
- account deletion flow

Production legal values are environment-driven:

```env
LEGAL_PROVIDER_NAME=...
LEGAL_PROVIDER_ADDRESS=...
LEGAL_CONTACT_EMAIL=...
LEGAL_PRIVACY_CONTACT_EMAIL=...
LEGAL_SUPERVISORY_AUTHORITY=...
LEGAL_LOG_RETENTION=14 Tage
```

The privacy documentation covers Gmail processing, optional Google Drive backup, AI processing and service-side logging. Final production legal wording should still be reviewed for the operator's actual jurisdiction and deployment.

## Development with Docker Compose

### Requirements

- Docker
- Docker Compose v2
- Google OAuth credentials for connected-account features

Create `.env` from `.env.example` and configure at least:

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

Start development services:

```bash
docker compose up --build
```

Current Compose services are:

- `db` — PostgreSQL 18
- `web` — Django development web service
- `gmail-assistant-worker` — automatic Gmail Assistant worker
- `backup-worker` — Google Drive personal-backup worker

Open <http://localhost:8000>.

Useful logs:

```bash
docker compose logs -f web
docker compose logs -f gmail-assistant-worker
docker compose logs -f backup-worker
```

## Production VPS deployment

The production layout targets Caddy, Gunicorn, local PostgreSQL and systemd. Detailed bootstrap/operations documentation is in [deploy/vps/README.md](deploy/vps/README.md).

Core units include:

- `jobapply-web.service` — Gunicorn/Django
- `jobapply-gmail-worker.service` — automatic Gmail Assistant sync
- `jobapply-drive-backup-worker.service` — personal Drive backup loop
- `jobapply-telegram-bot.service` — Telegram long polling
- `jobapply-deploy.service` — fixed deployment job
- `jobapply-demo-cleanup.timer` — expired demo cleanup
- `jobapply-backup.timer` — PostgreSQL backup
- `jobapply-neon-sync.timer` — optional recovery database sync

Install/update operational units after deployment changes:

```bash
cd /opt/jobapply
sudo bash deploy/vps/install-ops.sh
```

Production deployment is intentionally constrained:

- source branch must be `master`;
- working tree must be clean;
- update must be fast-forward;
- locked dependencies are installed;
- tests and Django checks run before activation;
- migrations and static collection run as part of deploy;
- known services are restarted;
- a health check runs after restart.

The owner-only Telegram `/deploy` command uses a one-time confirmation and can only start the fixed deployment service; it cannot inject an arbitrary branch or shell command.

Manual emergency deploy:

```bash
sudo /usr/local/sbin/jobapply-deploy
```

Inspect deployment output:

```bash
sudo journalctl -u jobapply-deploy.service -n 100 --no-pager -l
sudo tail -n 180 /var/log/jobapply/deploy-last.log
```

## Testing

Run the project quality gate in the same environment used by the application:

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

On the VPS, the deploy test phase temporarily grants only the PostgreSQL `CREATEDB` permission required to create the Django test database and revokes it afterwards.

After changing translatable UI strings:

```bash
python manage.py makemessages -l de
python manage.py compilemessages
```

## Configuration reference

`.env.example` is the source-controlled baseline for environment configuration. Important groups are:

- Django host/security settings
- PostgreSQL
- Google OAuth
- Turnstile
- demo lifetime/rate limits
- Gmail Assistant and OpenAI
- personal Drive backup interval
- Telegram bot/notifications/deploy
- legal provider/privacy values
- staff AI audit API

Do not put production secrets in the repository, screenshots, test fixtures or logs.

## Author

Maksym Petrykin
