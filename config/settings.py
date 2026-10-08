from pathlib import Path

import django_stubs_ext
import environ
from django.utils.csp import CSP

# Lets type-checked generics like UserAdmin[User] work at runtime.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")


# Core

SECRET_KEY = env.str("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
ADMIN_URL = env.str("ADMIN_URL", default="admin/")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "users.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "login"


# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "simple_history",
    "axes",
    "apps.users",
]

MIDDLEWARE = [
    # First, so container probes skip the HTTPS redirect and host validation.
    "config.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.middleware.NoStoreMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.users.context_processors.client_ip",
            ],
            "builtins": ["django.templatetags.static", "apps.icons.templatetags.icons"],
        },
    },
]


# Database

DATABASES = {"default": env.db_url("DATABASE_URL")}
DATABASES["default"] |= {
    "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
    "CONN_HEALTH_CHECKS": True,
    # Financial writes must never be half-applied.
    "ATOMIC_REQUESTS": True,
}


# Cache

CACHES = {"default": env.cache_url("CACHE_URL", default="locmemcache://")}


# Authentication

AUTHENTICATION_BACKENDS = [
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


# Brute-force protection
# Axes locks a username per IP after repeated failures; throttle caps total
# requests per IP so one address can't spray many usernames.

# Number of reverse proxies in front of the app that append to
# X-Forwarded-For. 0 means clients connect directly and REMOTE_ADDR is used.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)
AXES_CLIENT_IP_CALLABLE = "apps.users.client_ip.get_client_ip"

AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = env.int("AXES_COOLOFF_HOURS", default=1)
# Locking the pair, not the username alone, stops attackers from locking out
# real users from other addresses.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_CALLABLE = "apps.users.lockout.lockout_username"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/locked_out.html"

LOGIN_RATE_LIMIT = env.str("LOGIN_RATE_LIMIT", default="20/m")
PASSWORD_RESET_RATE_LIMIT = env.str("PASSWORD_RESET_RATE_LIMIT", default="5/h")


# Internationalization

LANGUAGE_CODE = env.str("LANGUAGE_CODE", default="en-us")
TIME_ZONE = env.str("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True


# Static and media files

STATIC_URL = env.str("STATIC_URL", default="static/")
STATIC_ROOT = env.path("STATIC_ROOT", default=BASE_DIR / "staticfiles")
# Built by the tailwind container (npm run build/watch); not in git.
STATICFILES_DIRS = [BASE_DIR / "static"]

# Written by `npm run vendor`.
LUCIDE_ICON_DIR = env.path("LUCIDE_ICON_DIR", default=BASE_DIR / "static" / "icons")
MEDIA_URL = env.str("MEDIA_URL", default="media/")
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# Security
# Secure by default; local development only needs DEBUG=True to relax these.

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

if env.bool("USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    # Error pages render without a request, so their <style> has no nonce.
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
}


# Email
# Lowercase names: Django 6.1 rejects legacy EMAIL_* settings alongside MAILERS.

email_backend = env.str(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
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
ADMINS = env.list("ADMINS", default=[])
MANAGERS = ADMINS


# Logging

LOG_LEVEL = env.str("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
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
