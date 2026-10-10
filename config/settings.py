"""Django settings for Velora.

Everything environment-specific is read from environment variables (or a
local `.env` file) through django-environ. Defaults are production-safe:
local development only needs `DEBUG=True` to relax the security settings.

Sections:
    1. Core                 6. Authentication and brute-force protection
    2. Applications         7. Internationalization
    3. Middleware           8. Static files and Attachments
    4. Templates            9. Security
    5. Database and cache  10. Email
                           11. Logging
                           12. AI Quick Add

Required variables: SECRET_KEY, DATABASE_URL, and the R2_* variables in
section 8 before any Attachment is uploaded or opened. CLOUDFLARE_* is optional.
"""

from pathlib import Path

import django_stubs_ext
import environ
from django.utils.csp import CSP

# Lets type-checked generics like UserAdmin[User] work at runtime.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")


# =============================================================================
# 1. Core
# =============================================================================

# WARNING: keep SECRET_KEY secret. It signs sessions, CSRF tokens and password
# reset links; leaking it lets an attacker forge all three. No default on
# purpose, so a missing key fails at startup instead of running insecurely.
SECRET_KEY = env.str("SECRET_KEY")

# WARNING: never enable DEBUG in production. It exposes settings, source and
# SQL in error pages, and it also relaxes the security defaults in section 9.
DEBUG = env.bool("DEBUG", default=False)

# Comma-separated hostnames this site may serve. Empty rejects every request
# when DEBUG is off.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
# Comma-separated origins (with scheme, e.g. https://velora.example.com) that
# may submit cross-origin POSTs. Needed when running behind a TLS proxy.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Moving the admin off /admin/ cuts down on automated probing. Must end in "/".
ADMIN_URL = env.str("ADMIN_URL", default="admin/")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "users.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "login"


# =============================================================================
# 2. Applications
# =============================================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # Must come before staticfiles so runserver serves files via WhiteNoise too.
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # Third party
    "simple_history",
    "axes",
    # Background jobs (ADR 0005); `manage.py procrastinate worker` runs them.
    "procrastinate.contrib.django",
    # Local
    "apps.users",
    "apps.classification",
    "apps.accounts",
    "apps.transactions",
    "apps.quick_add",
    "apps.schedules",
]


# =============================================================================
# 3. Middleware
# =============================================================================

# WARNING: order matters. Each entry only sees what the ones above it did.
MIDDLEWARE = [
    # First, so container probes skip the HTTPS redirect and host validation.
    "config.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Right after SecurityMiddleware, as WhiteNoise recommends.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Before anything that reads the request body.
    "config.middleware.RequestSizeMiddleware",
    "config.middleware.NoStoreMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.users.middleware.PrivacyModeAdminMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # Last, so it can see the final response of a failed login.
    "axes.middleware.AxesMiddleware",
]


# =============================================================================
# 4. Templates
# =============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                # Exposes the per-request CSP nonce as {{ csp_nonce }}.
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.quick_add.context_processors.quick_add",
            ],
            # Available in every template without {% load %}.
            "builtins": [
                "django.templatetags.static",
                "apps.users.templatetags.amounts",
            ],
        },
    },
]


# =============================================================================
# 5. Database and cache
# =============================================================================

# DATABASE_URL is required, e.g. postgres://user:pass@host:5432/velora
DATABASES = {"default": env.db_url("DATABASE_URL")}
DATABASES["default"] |= {
    # Seconds to keep a connection open between requests; 0 closes each time.
    "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
    # Drops dead persistent connections instead of failing the next request.
    "CONN_HEALTH_CHECKS": True,
    # Financial writes must never be half-applied.
    "ATOMIC_REQUESTS": True,
}

# WARNING: the default is per-process memory. With several workers each one
# has its own cache, so axes lockouts and rate limits are not shared. Set
# CACHE_URL to a shared backend (e.g. Redis) in production.
CACHES = {"default": env.cache_url("CACHE_URL", default="locmemcache://")}


# =============================================================================
# 6. Authentication and brute-force protection
# =============================================================================

AUTHENTICATION_BACKENDS = [
    # First, so it can block locked-out users before credentials are checked.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": env.int("PASSWORD_MIN_LENGTH", default=12)},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Axes locks a username per IP after repeated failures; throttle caps total
# requests per IP so one address can't spray many usernames.

# WARNING: must match the real number of reverse proxies in front of the app
# that append to X-Forwarded-For. Too high lets clients spoof their IP and
# dodge lockouts; too low makes every user appear as the proxy. 0 means
# clients connect directly and REMOTE_ADDR is used.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)
AXES_CLIENT_IP_CALLABLE = "apps.users.client_ip.get_client_ip"

# Failed attempts before lockout, and lockout duration in hours.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_HOURS", default=1)
# Locking the pair, not the username alone, stops attackers from locking out
# real users from other addresses.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_CALLABLE = "apps.users.lockout.lockout_username"
AXES_RESET_ON_SUCCESS = True

# Throttles in "count/period" form (s, m, h, d).
LOGIN_RATE_LIMIT = env.str("LOGIN_RATE_LIMIT", default="20/m")
PASSWORD_RESET_RATE_LIMIT = env.str("PASSWORD_RESET_RATE_LIMIT", default="5/h")


# =============================================================================
# 7. Internationalization
# =============================================================================

LANGUAGE_CODE = env.str("LANGUAGE_CODE", default="en-us")
TIME_ZONE = env.str("TIME_ZONE", default="UTC")
USE_I18N = True
# Store datetimes as UTC and convert on display.
USE_TZ = True


# =============================================================================
# 8. Static files and Attachments
# =============================================================================

# Static files are served by WhiteNoise; run `collectstatic` before deploying.
STATIC_URL = env.str("STATIC_URL", default="static/")
STATIC_ROOT = env.path("STATIC_ROOT", default=BASE_DIR / "staticfiles")
# Built by the tailwind container (npm run build/watch); not in git.
STATICFILES_DIRS = [BASE_DIR / "static"]

# Attachments live in a private Cloudflare R2 bucket, in dev (a separate test
# bucket) as in production (ADR 0004). Blank values only fail when storage is
# first used, so CI, tests and collectstatic run without R2 credentials.
# Each storage option, by the env var it comes from.
R2_ENV_VARS = {
    "endpoint_url": "R2_ENDPOINT_URL",
    "bucket_name": "R2_BUCKET_NAME",
    "access_key": "R2_ACCESS_KEY_ID",
    "secret_key": "R2_SECRET_ACCESS_KEY",
}
r2_options = {option: env.str(var, default="") for option, var in R2_ENV_VARS.items()}
CLOUDFLARE_ACCOUNT_ID = env.str("CLOUDFLARE_ACCOUNT_ID", default="")
CLOUDFLARE_API_TOKEN = env.str("CLOUDFLARE_API_TOKEN", default="")

STORAGES = {
    "default": {"BACKEND": "config.storage.R2Storage", "OPTIONS": r2_options},
    # Hashed filenames allow far-future caching, but a missing file referenced
    # by a template raises an error instead of a silent 404.
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# =============================================================================
# 9. Security
# =============================================================================

# Secure by default; local development only needs DEBUG=True to relax these.

# --- HTTPS ---
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)

# WARNING: HSTS is sticky. Browsers refuse plain HTTP for this host for the
# whole duration (a year by default), so confirm HTTPS works before deploying.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG
)
# WARNING: preload is effectively permanent once browsers ship the list.
# Only enable after submitting the domain to hstspreload.org.
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

# Enable only when the proxy sets X-Forwarded-Proto itself and strips any
# client-supplied value; otherwise clients can fake HTTPS.
if env.bool("USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Cookies and framing ---
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# --- Content Security Policy ---
# Inline scripts and styles only run with the per-request nonce. Adding
# "unsafe-inline" here would defeat the policy.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    # The admin change list has a nonced <style> block.
    "style-src": [CSP.SELF, CSP.NONCE],
    # Attachment previews redirect to presigned R2 links.
    "img-src": [CSP.SELF, "data:", *filter(None, [r2_options["endpoint_url"]])],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
}


# =============================================================================
# 10. Email
# =============================================================================

# Lowercase names: Django 6.1 rejects legacy EMAIL_* settings alongside MAILERS.

# Prints to the console in development, SMTP otherwise.
email_backend = env.str(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
# SMTP options are only valid for the SMTP backend; others reject them.
email_options = (
    {
        "host": env.str("EMAIL_HOST", default="localhost"),
        "port": env.int("EMAIL_PORT", default=587),
        "username": env.str("EMAIL_HOST_USER", default=""),
        "password": env.str("EMAIL_HOST_PASSWORD", default=""),
        "use_tls": env.bool("EMAIL_USE_TLS", default=True),
        "use_ssl": env.bool("EMAIL_USE_SSL", default=False),
        "timeout": env.int("EMAIL_TIMEOUT", default=10),
    }
    if email_backend.endswith("smtp.EmailBackend")
    else {}
)
MAILERS = {"default": {"BACKEND": email_backend, "OPTIONS": email_options}}

DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="webmaster@localhost")
SERVER_EMAIL = env.str("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = env.str("EMAIL_SUBJECT_PREFIX", default="[Velora] ")

# Receive 500-error emails (see mail_admins in section 11).
ADMINS = env.list("ADMINS", default=[])
MANAGERS = ADMINS


# =============================================================================
# 11. Logging
# =============================================================================

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    # Keep third-party loggers working instead of silencing them.
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "mail_admins": {
            "class": "django.utils.log.AdminEmailHandler",
            "level": "ERROR",
            "filters": ["require_debug_false"],
        },
    },
    "filters": {
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {
            "handlers": ["console", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}


# =============================================================================
# 12. AI Quick Add
# =============================================================================

# Quick Add is hidden entirely while the key is empty.
OPENROUTER_API_KEY = env.str("OPENROUTER_API_KEY", default="")
# Must support structured output (response_format JSON schema, strict: true).
OPENROUTER_MODEL = env.str("OPENROUTER_MODEL", default="openai/gpt-6-luna")
# Some models (gpt-5 family, gpt-oss) reject "none", hence "low".
OPENROUTER_REASONING_EFFORT = env.str("OPENROUTER_REASONING_EFFORT", default="low")
