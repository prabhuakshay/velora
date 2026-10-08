import pytest
from django.conf import settings

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


@pytest.fixture
def user(db: None) -> User:
    return User.objects.create_user("user@example.com", PASSWORD, full_name="Test User")


@pytest.fixture
def superuser(db: None) -> User:
    return User.objects.create_superuser(
        "admin@example.com", PASSWORD, full_name="Admin"
    )
