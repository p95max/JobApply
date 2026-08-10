from __future__ import annotations
from os import getenv

import os

from pathlib import Path
from dotenv import load_dotenv
from django.utils.translation import gettext_lazy as _

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-secret-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0.")
if not DEBUG and (SECRET_KEY == "dev-secret-key" or len(SECRET_KEY) < 50):
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be a non-development value of at least 50 characters."
    )
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

USE_X_FORWARDED_HOST = getenv("DJANGO_USE_X_FORWARDED_HOST", "0") == "1"
if getenv("DJANGO_SECURE_PROXY_SSL_HEADER", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = max(0, int(getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000")))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "widget_tweaks",
    "django.contrib.sites",
    "apps.accounts.apps.AccountsConfig",
    "apps.applications",
    "apps.interviews",
    "apps.reports",
    "apps.gmail_stats",
    "apps.gmail_assistant.apps.GmailAssistantConfig",
    "apps.telegram_bot.apps.TelegramBotConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.security.middleware.TurnstileAnonymousGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.accounts.middleware.DemoUserRestrictionsMiddleware",
    "apps.accounts.middleware.ConsentRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.account_mode",
                "apps.gmail_assistant.context_processors.gmail_assistant_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "jobapply"),
        "USER": os.getenv("POSTGRES_USER", "jobapply"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "jobapply"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

LANGUAGES = [("en", _("English")), ("de", _("Deutsch"))]
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [p for p in [BASE_DIR / "static"] if p.exists()]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1

LOGIN_URL = "/accounts/google/login/"
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_BY_CODE_ENABLED = False
ACCOUNT_PASSWORD_REQUIRED = False
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = []
SILENCED_SYSTEM_CHECKS = ["account.W001"]
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_ADAPTER = "apps.accounts.adapters.NoSignupAccountAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = True
# The Google button is already an explicit consent action in our UI. Do not
# show allauth's second generic "Continue" page before redirecting to Google.
SOCIALACCOUNT_LOGIN_ON_GET = True

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
        "AUTH_PARAMS": {"access_type": "offline", "prompt": "consent"},
    }
}

SOCIALACCOUNT_STORE_TOKENS = True
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.CustomSocialAccountAdapter"
AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

TURNSTILE_SITE_KEY = getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = getenv("TURNSTILE_SECRET_KEY", "")
TURNSTILE_ENABLED = getenv("TURNSTILE_ENABLED", "1") == "1"
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

try:
    DEMO_ACCOUNT_TTL_HOURS = max(1, int(getenv("DEMO_ACCOUNT_TTL_HOURS", "12")))
except ValueError:
    DEMO_ACCOUNT_TTL_HOURS = 12

GMAIL_ASSISTANT_AI_ENABLED = getenv("GMAIL_ASSISTANT_AI_ENABLED", "0") == "1"
GMAIL_ASSISTANT_AUTO_SYNC_ENABLED = getenv("GMAIL_ASSISTANT_AUTO_SYNC_ENABLED", "1") == "1"
try:
    GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS = max(
        60, int(getenv("GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS", "900"))
    )
except ValueError:
    GMAIL_ASSISTANT_AUTO_SYNC_INTERVAL_SECONDS = 900
try:
    GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS = max(
        10, int(getenv("GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS", "60"))
    )
except ValueError:
    GMAIL_SYNC_MANUAL_COOLDOWN_SECONDS = 60
try:
    GMAIL_SYNC_LOCK_TIMEOUT_SECONDS = max(
        60, int(getenv("GMAIL_SYNC_LOCK_TIMEOUT_SECONDS", "1800"))
    )
except ValueError:
    GMAIL_SYNC_LOCK_TIMEOUT_SECONDS = 1800
try:
    PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS = max(
        300, int(getenv("PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS", "21600"))
    )
except ValueError:
    PERSONAL_DRIVE_BACKUP_INTERVAL_SECONDS = 21600
GMAIL_ASSISTANT_DEV_TOOLS = getenv("GMAIL_ASSISTANT_DEV_TOOLS", "0") == "1"
TELEGRAM_OWNER_EMAIL = getenv("TELEGRAM_OWNER_EMAIL", "").strip()
OPENAI_API_KEY = getenv("OPENAI_API_KEY", "")
OPENAI_EMAIL_MODEL = getenv("OPENAI_EMAIL_MODEL", "gpt-5.4-nano")
try:
    GMAIL_ASSISTANT_AI_DAILY_LIMIT = max(0, int(getenv("GMAIL_ASSISTANT_AI_DAILY_LIMIT", "50")))
except ValueError:
    GMAIL_ASSISTANT_AI_DAILY_LIMIT = 50
try:
    GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD = min(
        100,
        max(0, int(getenv("GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD", "80"))),
    )
except ValueError:
    GMAIL_ASSISTANT_AI_CONFIDENCE_THRESHOLD = 80
GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED = getenv("GMAIL_ASSISTANT_RULES_FALLBACK_ENABLED", "1") == "1"

TELEGRAM_BOT_USERNAME = getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
try:
    TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS = max(
        10, int(getenv("TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS", "60"))
    )
except ValueError:
    TELEGRAM_LINK_TOKEN_COOLDOWN_SECONDS = 60
try:
    APPLICATION_BULK_DELETE_MAX_IDS = max(
        1, min(500, int(getenv("APPLICATION_BULK_DELETE_MAX_IDS", "200")))
    )
except ValueError:
    APPLICATION_BULK_DELETE_MAX_IDS = 200
try:
    CSV_IMPORT_DAILY_LIMIT = max(1, min(20, int(getenv("CSV_IMPORT_DAILY_LIMIT", "3"))))
except ValueError:
    CSV_IMPORT_DAILY_LIMIT = 3
try:
    CSV_IMPORT_COOLDOWN_SECONDS = max(10, int(getenv("CSV_IMPORT_COOLDOWN_SECONDS", "60")))
except ValueError:
    CSV_IMPORT_COOLDOWN_SECONDS = 60
try:
    DRIVE_MANUAL_OPERATION_DAILY_LIMIT = max(
        1, min(100, int(getenv("DRIVE_MANUAL_OPERATION_DAILY_LIMIT", "20")))
    )
except ValueError:
    DRIVE_MANUAL_OPERATION_DAILY_LIMIT = 20
try:
    DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS = max(
        10, int(getenv("DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS", "30"))
    )
except ValueError:
    DRIVE_MANUAL_OPERATION_COOLDOWN_SECONDS = 30

LEGAL_PROVIDER_NAME = getenv("LEGAL_PROVIDER_NAME", "[Bitte Namen der verantwortlichen Person eintragen]").strip()
LEGAL_PROVIDER_ADDRESS = getenv("LEGAL_PROVIDER_ADDRESS", "[Bitte ladungsfähige Anschrift eintragen]").strip()
LEGAL_CONTACT_EMAIL = getenv("LEGAL_CONTACT_EMAIL", "[Bitte Kontakt-E-Mail eintragen]").strip()
LEGAL_PRIVACY_CONTACT_EMAIL = getenv("LEGAL_PRIVACY_CONTACT_EMAIL", LEGAL_CONTACT_EMAIL).strip()
LEGAL_SUPERVISORY_AUTHORITY = getenv(
    "LEGAL_SUPERVISORY_AUTHORITY", "[Bitte zuständige Datenschutz-Aufsichtsbehörde eintragen]"
).strip()
LEGAL_LOG_RETENTION = getenv("LEGAL_LOG_RETENTION", "[Bitte Aufbewahrungsdauer für Server-Logs eintragen]").strip()

ADMIN_URL = os.getenv("ADMIN_URL", "admin").strip("/")
