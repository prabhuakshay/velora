"""What a Party's or Tag's Splits added up to: in all, by month and by where."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Case, F, Max, Min, Q, Sum, When
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.accounts.activity import MONTHS
from apps.accounts.models import Account
from apps.classification.models import earned, spent
from apps.core.dates import months_after

if TYPE_CHECKING:
    from datetime import date

    from django.db.models import QuerySet

    from apps.transactions.models import Split

SHARES_SHOWN = 5


@dataclass(frozen=True)
class Share:
    """One Account's or Party's part of the money, linked to its page."""

    name: str
    url: str
    total: Decimal
    percent: int


@dataclass(frozen=True)
class Activity:
    """The Splits' money, measured the way it mostly went.

    earns is whether more was earned than spent, all time; total is all time
    that way, and other the other way. months holds the last MONTHS months,
    oldest first, as (start, total).
    """

    earns: bool
    total: Decimal
    other: Decimal
    first: date | None
    last: date | None
    months: list[tuple[date, Decimal]]
    accounts: list[Share]
    more_accounts: int

    @property
    def this_month(self) -> Decimal:
        """This month's total."""
        return self.months[-1][1]

    @property
    def last_month(self) -> Decimal:
        """Last month's total."""
        return self.months[-2][1]

    @property
    def year(self) -> Decimal:
        """The total over the last MONTHS months, this one included."""
        return sum((total for _, total in self.months), Decimal(0))

    @property
    def average(self) -> Decimal:
        """The monthly average over the last MONTHS months."""
        return self.year / MONTHS


def _shares(rows: list[tuple[str, str, Decimal]]) -> list[Share]:
    whole = sum((total for _, _, total in rows if total > 0), Decimal(0))
    return [
        Share(
            name=name,
            url=url,
            total=total,
            percent=round(total / whole * 100) if whole and total > 0 else 0,
        )
        for name, url, total in rows
    ]


def activity(splits: QuerySet[Split], today: date) -> Activity:
    """Sum the Splits all time, by month and by Expense or Income Account."""
    totals = splits.aggregate(
        spent=Sum(spent(), default=Decimal(0)),
        earned=Sum(earned(), default=Decimal(0)),
        first=Min("transaction__date"),
        last=Max("transaction__date"),
    )
    earns = totals["earned"] > totals["spent"]
    measure = earned() if earns else spent()
    first_month = months_after(today.replace(day=1), 1 - MONTHS)
    by_month = dict(
        splits.filter(transaction__date__gte=first_month)
        .annotate(month=TruncMonth("transaction__date"))
        .order_by()
        .values("month")
        .annotate(total=Sum(measure))
        .values_list("month", "total")
    )
    kind = Account.Kind.INCOME if earns else Account.Kind.EXPENSE
    by_account = list(
        splits.filter(Q(to_account__kind=kind) | Q(from_account__kind=kind))
        .annotate(
            account=Case(
                When(to_account__kind=kind, then=F("to_account")),
                default=F("from_account"),
            )
        )
        .order_by()
        .values("account")
        .annotate(total=Sum(measure))
        .order_by("-total")
        .values_list("account", "total")
    )
    accounts = Account.objects.in_bulk([pk for pk, _ in by_account])
    shares = _shares(
        [
            (
                accounts[pk].name,
                reverse("account_transactions", args=[kind, pk]),
                total,
            )
            for pk, total in by_account
        ]
    )
    return Activity(
        earns=earns,
        total=totals["earned"] if earns else totals["spent"],
        other=totals["spent"] if earns else totals["earned"],
        first=totals["first"],
        last=totals["last"],
        months=[
            (start, by_month.get(start, Decimal(0)))
            for start in (months_after(first_month, i) for i in range(MONTHS))
        ],
        accounts=shares[:SHARES_SHOWN],
        more_accounts=max(len(shares) - SHARES_SHOWN, 0),
    )


def party_shares(splits: QuerySet[Split], *, earns: bool) -> list[Share]:
    """The Parties the Splits' Transactions were with, biggest first."""
    rows = (
        splits.filter(transaction__party__isnull=False)
        .order_by()
        .values("transaction__party", "transaction__party__name")
        .annotate(total=Sum(earned() if earns else spent()))
        .filter(total__gt=0)
        .order_by("-total")
        .values_list("transaction__party", "transaction__party__name", "total")
    )
    shares = _shares(
        [
            (name, reverse("party_transactions", args=[pk]), total)
            for pk, name, total in rows
        ]
    )
    return shares[:SHARES_SHOWN]
