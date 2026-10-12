import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.accounts.tests.conftest import page_text
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

    from apps.accounts.models import Account

JUNE = date(2026, 6, 1)
TODAY = date(2026, 6, 15)


def move(when: date, source: Account, destination: Account, amount: str) -> None:
    transaction = Transaction.objects.create(date=when)
    Split.objects.create(
        transaction=transaction,
        from_account=source,
        to_account=destination,
        amount=Decimal(amount),
    )


def cell(page: str, label: str) -> str | None:
    """The value in the Budget cell with that label; None when there's no cell."""
    for tag in re.findall(r"<input\b[^>]*>", page):
        if f'aria-label="{label}"' in tag:
            value = re.search(r'value="([^"]*)"', tag)
            return value[1] if value else ""
    return None


def swapped(response: Response) -> dict[str, str]:
    """The text of each part a save sends back to swap in place, by its id."""
    # Each part runs to its closing tag just before the next part or the end,
    # so parts may nest elements of their own tag.
    parts = re.findall(
        r'<(\w+) id="([^"]+)" hx-swap-oob="true"[^>]*>(.*?)</\1>\s*'
        r'(?=<\w+ id="[^"]+" hx-swap-oob|$)',
        response.content.decode(),
        re.DOTALL,
    )
    return {fid: page_text(html) for _, fid, html in parts}
