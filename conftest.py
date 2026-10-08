import pytest
from django.conf import settings
from django.core.cache import cache

from apps.users.models import User

PASSWORD = "correct-horse-battery-staple"


def pytest_configure() -> None:
    # The manifest storage needs collectstatic, which tests don't run.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    # Defaults to on unless DEBUG, which made tests pass only with a local .env
    # setting DEBUG=True; the test client speaks plain HTTP and got 301s.
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # Rate-limit counters live in the cache and would leak between tests.
    cache.clear()


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user("user@example.com", PASSWORD, full_name="Test User")


@pytest.fixture
def other_user(db: None) -> User:
    return User.objects.create_user("other@example.com", PASSWORD, full_name="Other")


@pytest.fixture
def superuser(db: None) -> User:
    return User.objects.create_superuser(
        "admin@example.com", PASSWORD, full_name="Admin"
    )
