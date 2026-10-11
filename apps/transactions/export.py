"""Exporting Transactions to CSV."""

import csv
from typing import TYPE_CHECKING

from django.http import HttpResponse

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.transactions.models import Transaction

HEADER = ["Date", "Party", "Description", "From", "To", "Amount", "Tags"]


def transactions_csv(transactions: QuerySet[Transaction]) -> HttpResponse:
    """A CSV download with one row per Split, so every amount keeps its Accounts."""
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )
    writer = csv.writer(response)
    writer.writerow(HEADER)
    for transaction in transactions:
        for split in transaction.splits.all():
            writer.writerow(
                [
                    transaction.date.isoformat(),
                    transaction.party.name if transaction.party else "",
                    transaction.description,
                    split.from_account.name,
                    split.to_account.name,
                    split.amount,
                    ", ".join(tag.name for tag in split.tags.all()),
                ]
            )
    return response
