"""Classification models: parties and tags."""

from typing import TYPE_CHECKING, Any, ClassVar, Self

from django.apps import apps
from django.db import models
from django.db.models.functions import Coalesce, Lower
from simple_history.models import HistoricalRecords

from apps.accounts.models import AccountKind

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from decimal import Decimal

MONEY = models.DecimalField(max_digits=15, decimal_places=2)


def _signed(kind: AccountKind, *, into: bool) -> models.Case:
    """A Split's amount toward kind's Accounts, negative coming back from them.

    into=True counts money going to them (spending, for Expense Accounts);
    into=False counts money coming from them (earning, for Income Accounts).
    """
    toward, back = (
        ("to_account", "from_account") if into else ("from_account", "to_account")
    )
    return models.Case(
        models.When(**{f"{toward}__kind": kind}, then=models.F("amount")),
        models.When(**{f"{back}__kind": kind}, then=-models.F("amount")),
        default=models.Value(0),
        output_field=MONEY,
    )


def spent() -> models.Case:
    """A Split's amount spent: into an Expense Account, less Refunds out of one."""
    return _signed(AccountKind.EXPENSE, into=True)


def earned() -> models.Case:
    """A Split's amount earned: out of an Income Account, less any sent back."""
    return _signed(AccountKind.INCOME, into=False)


def _over(
    rows: models.QuerySet[Any],
    function: str,
    expression: object,
    field: models.Field[Any, Any],
) -> models.Subquery:
    # A plain aggregate with no GROUP BY, so the subquery is always one row.
    # Used for counts and dates too: Count and Max over a join would make the
    # outer query GROUP BY the money subqueries, running them once per row.
    value = models.Func(expression, function=function, output_field=field)
    return models.Subquery(rows.order_by().annotate(value=value).values("value")[:1])


def _split_totals(link: str, since: date | None) -> dict[str, Coalesce]:
    # Looked up by name: the transactions app imports this module.
    split = apps.get_model("transactions", "Split")
    splits = split.objects.filter(**{link: models.OuterRef("pk")})
    if since is not None:
        splits = splits.filter(transaction__date__gte=since)

    def total(expression: models.Case) -> Coalesce:
        return Coalesce(
            _over(splits, "SUM", expression, MONEY), models.Value(0), output_field=MONEY
        )

    return {"spent": total(spent()), "earned": total(earned())}


# Full class names, so Tailwind finds them when scanning this file.
SWATCH_CLASSES = {
    "slate": "bg-slate-600",
    "red": "bg-red-600",
    "orange": "bg-orange-600",
    "amber": "bg-amber-600",
    "green": "bg-green-600",
    "cyan": "bg-cyan-600",
    "blue": "bg-blue-600",
    "violet": "bg-violet-600",
    "pink": "bg-pink-600",
}


class PartyQuerySet(models.QuerySet["Party"]):
    """Queries over Parties."""

    def with_usage(self, since: date | None = None) -> Self:
        """Annotate each Party's Transaction count and newest date, all time.

        And its money spent and earned, on or after since if given.
        """
        transaction = apps.get_model("transactions", "Transaction")
        rows = transaction.objects.filter(party=models.OuterRef("pk"))
        return self.annotate(
            transaction_count=_over(
                rows, "COUNT", models.F("pk"), models.IntegerField()
            ),
            last_used=_over(rows, "MAX", models.F("date"), models.DateField()),
            **_split_totals("transaction__party", since),
        )


class Party(models.Model):
    """Someone outside the user who money is paid to or received from."""

    name = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)

    objects = PartyQuerySet.as_manager()
    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]
    # Set only on Parties fetched through with_usage().
    transaction_count: int
    last_used: date | None
    spent: Decimal
    earned: Decimal

    class Meta:
        verbose_name_plural = "parties"
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), name="classification_party_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class TagQuerySet(models.QuerySet["Tag"]):
    """Queries over Tags."""

    def with_usage(self, since: date | None = None) -> Self:
        """Annotate each Tag's Split count and newest date, all time.

        And the money spent and earned on its Splits, on or after since if given.
        """
        split = apps.get_model("transactions", "Split")
        rows = split.objects.filter(tags=models.OuterRef("pk"))
        return self.annotate(
            split_count=_over(rows, "COUNT", models.F("pk"), models.IntegerField()),
            last_used=_over(
                rows, "MAX", models.F("transaction__date"), models.DateField()
            ),
            **_split_totals("tags", since),
        )


class Tag(models.Model):
    """A free-form label for grouping money movements."""

    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=16,
        choices=[(name, name.title()) for name in SWATCH_CLASSES],
        default="slate",
    )
    hidden = models.BooleanField(default=False)

    objects = TagQuerySet.as_manager()
    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]
    # Set only on Tags fetched through with_usage().
    split_count: int
    last_used: date | None
    spent: Decimal
    earned: Decimal

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), name="classification_tag_name_ci_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def swatch_class(self) -> str:
        """Tailwind background class for the tag's colour."""
        return SWATCH_CLASSES[self.color]
