from typing import IO, TYPE_CHECKING, Any

import pytest
from django.core.files.storage import InMemoryStorage, default_storage
from django.urls import reverse

if TYPE_CHECKING:
    from pytest_django import Settings

    from apps.accounts.models import Account
    from apps.transactions.models import Transaction


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


def stored_names() -> list[str]:
    """Every file name in the default storage's attachments directory."""
    try:
        _, files = default_storage.listdir("attachments")
    except FileNotFoundError:
        return []
    return sorted(f"attachments/{name}" for name in files)


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
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "apps.transactions.tests.conftest.SecondSaveFailsStorage"
        },
    }


class DeleteFailsStorage(InMemoryStorage):
    """Stores files but can't delete them, like an outage mid-delete."""

    def delete(self, name: str) -> None:
        msg = "storage unavailable"
        raise OSError(msg)


@pytest.fixture
def delete_fails(settings: Settings) -> None:
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "apps.transactions.tests.conftest.DeleteFailsStorage"},
    }


class SecondDeleteFailsStorage(InMemoryStorage):
    """Deletes one file, fails once, then recovers; missing files raise.

    Raising on a missing file, as some backends do, checks that a retry
    treats a file already gone as deleted.
    """

    deletes = 0

    def delete(self, name: str) -> None:
        self.deletes += 1
        if self.deletes == 2:
            msg = "storage unavailable"
            raise OSError(msg)
        if not self.exists(name):
            raise FileNotFoundError(name)
        super().delete(name)


@pytest.fixture
def second_delete_fails(settings: Settings) -> None:
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {
            "BACKEND": "apps.transactions.tests.conftest.SecondDeleteFailsStorage"
        },
    }
