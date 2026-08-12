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
