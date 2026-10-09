from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.core.cache import cache

from apps.users.models import User

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

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
def _in_memory_storage(settings: Settings) -> None:
    # A fresh, empty storage per test, so files never touch disk or leak.
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # Rate-limit counters live in the cache and would leak between tests.
    cache.clear()


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user("user@example.com", PASSWORD, full_name="Test User")


@pytest.fixture
def superuser(db: None) -> User:
    return User.objects.create_superuser(
        "admin@example.com", PASSWORD, full_name="Admin"
    )


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client
