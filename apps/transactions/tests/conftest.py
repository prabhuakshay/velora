from typing import TYPE_CHECKING, Any

from django.urls import reverse

if TYPE_CHECKING:
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
