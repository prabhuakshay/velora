import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError
from django.test import Client

from apps.users.models import User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_create_user_lowercases_email() -> None:
    user = User.objects.create_user("Mixed@Example.COM", PASSWORD)

    assert user.email == "mixed@example.com"
    assert user.check_password(PASSWORD)
    assert not user.is_staff
    assert not user.is_superuser


def test_create_user_requires_email() -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("", PASSWORD)


def test_create_superuser_sets_flags(superuser: User) -> None:
    assert superuser.is_staff
    assert superuser.is_superuser


def test_email_is_unique_ignoring_case(user: User) -> None:
    with pytest.raises(IntegrityError):
        User.objects.create(email=user.email.upper())


def test_authenticate_ignores_email_case(user: User) -> None:
    assert authenticate(username=user.email.upper(), password=PASSWORD) == user


def test_clean_normalizes_email() -> None:
    user = User(email="Someone@EXAMPLE.com")

    user.clean()

    assert user.email == "someone@example.com"


def test_names(user: User) -> None:
    assert str(user) == "user@example.com"
    assert user.get_full_name() == "Test User"
    assert user.get_short_name() == "Test User"


def test_edit_creates_history(user: User) -> None:
    user.full_name = "Renamed"
    user.save()

    assert user.history.count() == 2
    assert user.history.first().full_name == "Renamed"


def test_login_does_not_create_history(user: User) -> None:
    Client().login(username=user.email, password=PASSWORD)

    user.refresh_from_db()
    assert user.last_login is not None
    assert user.history.count() == 1


def test_history_omits_sensitive_and_noisy_fields() -> None:
    field_names = {field.name for field in User.history.model._meta.fields}

    assert "password" not in field_names
    assert "last_login" not in field_names
