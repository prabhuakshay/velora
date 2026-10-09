"""Custom user model that signs in by email."""

from typing import TYPE_CHECKING, ClassVar, override

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable


class UserManager(BaseUserManager["User"]):
    """Create users keyed by a lowercased email."""

    def create_user(
        self, email: str, password: str | None = None, **extra_fields: object
    ) -> User:
        """Create a user with a lowercased email and the given password."""
        if not email:
            msg = "Users must have an email address."
            raise ValueError(msg)
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: object
    ) -> User:
        """Create a user with staff and superuser rights."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)

    @override
    def get_by_natural_key(self, username: str | None) -> User:
        return self.get(email=self.normalize_email(username).lower())


class NumberFormat(models.TextChoices):
    """How amounts are grouped when shown."""

    INDIAN = "indian", "Indian (₹12,34,567.89)"
    INTERNATIONAL = "international", "International (₹1,234,567.89)"


class User(AbstractBaseUser, PermissionsMixin):
    """A person who signs in with their email address."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)
    number_format = models.CharField(
        max_length=13, choices=NumberFormat, default=NumberFormat.INDIAN
    )
    privacy_mode = models.BooleanField(default=False)

    # Old password hashes in history would be a needless leak, and frequent
    # Privacy Mode toggling would bury real changes.
    history = HistoricalRecords(
        excluded_fields=["last_login", "password", "privacy_mode"]
    )
    save_without_historical_record: Callable[..., None]

    objects: ClassVar[UserManager] = UserManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["full_name"]

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(Lower("email"), name="users_user_email_ci_unique"),
        ]

    def __str__(self) -> str:
        return self.email

    @override
    def clean(self) -> None:
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).lower()

    def set_privacy_mode(self, *, on: bool) -> None:
        """Turn Privacy Mode on or off, leaving no history row."""
        self.privacy_mode = on
        self.save_without_historical_record(update_fields=["privacy_mode"])

    def get_full_name(self) -> str:
        """The user's full name, for the admin."""
        return self.full_name

    def get_short_name(self) -> str:
        """The user's full name; there is no shorter form."""
        return self.full_name
