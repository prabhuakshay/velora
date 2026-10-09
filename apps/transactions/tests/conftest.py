from datetime import date
from decimal import Decimal
from typing import IO, TYPE_CHECKING, Any

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Attachment, Transaction

if TYPE_CHECKING:
    from pytest_django import Settings

    from apps.accounts.models import Account


def form_data(
    source: Account, destination: Account, amount: str = "100.00", **fields: Any
) -> dict[str, Any]:
    split_id = fields.pop("split_id", "")
    return {
        "date": "2026-03-01",
        "party": "",
        "description": "",
        "splits-TOTAL_FORMS": "1",
        "splits-INITIAL_FORMS": "1" if split_id else "0",
        "splits-0-id": split_id,
        "splits-0-from_account": source.pk,
        "splits-0-to_account": destination.pk,
        "splits-0-amount": amount,
        **fields,
    }


def row(
    source: Account, destination: Account, amount: str = "100.00", **fields: Any
) -> dict[str, Any]:
    return {
        "from_account": source.pk,
        "to_account": destination.pk,
        "amount": amount,
        **fields,
    }


def split_rows(
    *rows: dict[str, Any], initial: int = 0, **fields: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "date": "2026-03-01",
        "party": "",
        "description": "",
        "splits-TOTAL_FORMS": str(len(rows)),
        "splits-INITIAL_FORMS": str(initial),
        **fields,
    }
    for index, values in enumerate(rows):
        for name, value in values.items():
            data[f"splits-{index}-{name}"] = value
    return data


def transaction_url(name: str, transaction: Transaction) -> str:
    return reverse(name, kwargs={"pk": transaction.pk})


def recorded(description: str = "") -> Transaction:
    """A Transaction with one Split between Accounts named after it."""
    transaction = Transaction.objects.create(
        date=date(2026, 3, 1), description=description
    )
    transaction.splits.create(
        from_account=make_account(f"Bank {description}".strip(), "asset"),
        to_account=make_account(f"Groceries {description}".strip(), "expense"),
        amount=Decimal(100),
    )
    return transaction


def attach(
    transaction: Transaction,
    name: str = "bill.pdf",
    content: bytes = b"%PDF bill",
    content_type: str = "application/pdf",
) -> Attachment:
    """An Attachment written straight to storage, skipping the form."""
    attachment = Attachment(
        transaction=transaction,
        original_name=name,
        content_type=content_type,
        size=len(content),
    )
    attachment.file.save(name, ContentFile(content), save=False)
    attachment.save()
    return attachment


def upload(name: str, content: bytes) -> SimpleUploadedFile:
    # The browser's content type is ignored, so any will do.
    return SimpleUploadedFile(name, content, "application/octet-stream")


def stored_names() -> list[str]:
    """Every file name in the default storage's attachments directory."""
    try:
        _, files = default_storage.listdir("attachments")
    except FileNotFoundError:
        return []
    return sorted(f"attachments/{name}" for name in files)


def use_storage(settings: Settings, backend: str, **options: str) -> None:
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": backend, "OPTIONS": options},
    }


class SecondSaveFailsStorage(InMemoryStorage):
    """Stores the first file, then fails, like an outage mid-upload."""

    saves = 0

    def save(
        self, name: str | None, content: IO[Any], max_length: int | None = None
    ) -> str:
        self.saves += 1
        if self.saves > 1:
            msg = "storage unavailable"
            raise OSError(msg)
        return super().save(name, content, max_length)


@pytest.fixture
def second_save_fails(settings: Settings) -> None:
    use_storage(settings, f"{__name__}.SecondSaveFailsStorage")


class DeleteFailsStorage(InMemoryStorage):
    """Stores files but can't delete them, like an outage mid-delete."""

    def delete(self, name: str) -> None:
        msg = "storage unavailable"
        raise OSError(msg)


@pytest.fixture
def delete_fails(settings: Settings) -> None:
    use_storage(settings, f"{__name__}.DeleteFailsStorage")


class MissingRaisesStorage(InMemoryStorage):
    """Raises on deleting a file that isn't there, as some backends do."""

    def delete(self, name: str) -> None:
        if not self.exists(name):
            raise FileNotFoundError(name)
        super().delete(name)


@pytest.fixture
def missing_raises(settings: Settings) -> None:
    use_storage(settings, f"{__name__}.MissingRaisesStorage")


class SecondDeleteFailsStorage(MissingRaisesStorage):
    """Deletes one file, fails once, then recovers."""

    deletes = 0

    def delete(self, name: str) -> None:
        self.deletes += 1
        if self.deletes == 2:
            msg = "storage unavailable"
            raise OSError(msg)
        super().delete(name)


@pytest.fixture
def second_delete_fails(settings: Settings) -> None:
    use_storage(settings, f"{__name__}.SecondDeleteFailsStorage")


def fail_next_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next database commit fail, like a connection lost at the end.

    Only reaches a real commit in a django_db(transaction=True) test.
    """
    commit = connection.commit

    def fail() -> None:
        monkeypatch.setattr(connection, "commit", commit)
        msg = "connection lost"
        raise OperationalError(msg)

    monkeypatch.setattr(connection, "commit", fail)


R2_ENDPOINT = "https://account.r2.cloudflarestorage.com"


@pytest.fixture
def r2_storage(settings: Settings) -> None:
    """The real R2 backend with dummy credentials: presigning needs no network."""
    use_storage(
        settings,
        "config.storage.R2Storage",
        endpoint_url=R2_ENDPOINT,
        bucket_name="velora-test",
        access_key="test-key",
        secret_key="test-secret",
    )
