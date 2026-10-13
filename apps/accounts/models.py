"""Accounts: anything money moves from or to."""

from typing import TYPE_CHECKING, ClassVar, Self

from django.apps import apps
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Coalesce, Lower
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from decimal import Decimal


class AccountKind(models.TextChoices):
    """What an Account is: Asset, Liability, Expense or Income."""

    ASSET = "asset"
    LIABILITY = "liability"
    EXPENSE = "expense"
    INCOME = "income"


BALANCE_KINDS = (AccountKind.ASSET, AccountKind.LIABILITY)
# Money moving out of these grows them: what is owed, or what is earned.
OWING_KINDS = (AccountKind.LIABILITY, AccountKind.INCOME)
# Clamped to the last day of shorter months.
DAY_OF_MONTH = [MinValueValidator(1), MaxValueValidator(31)]
MONEY = models.DecimalField(max_digits=15, decimal_places=2)


def _split_total(
    account_field: str,
    as_of: date | models.F | None,
    since: date | None = None,
    account: str = "pk",
) -> Coalesce:
    # Looked up by name: the transactions app imports this module.
    split = apps.get_model("transactions", "Split")
    splits = split.objects.filter(**{account_field: models.OuterRef(account)})
    if as_of is not None:
        splits = splits.filter(transaction__date__lte=as_of)
    if since is not None:
        splits = splits.filter(transaction__date__gte=since)
    totals = (
        splits.values(account_field)
        .annotate(total=models.Sum("amount"))
        .values("total")
    )
    return Coalesce(models.Subquery(totals), models.Value(0), output_field=MONEY)


def _balance(as_of: date | str | None, account: str = "") -> models.Expression:
    """An Account's Balance at the end of as_of; a Liability's is what is owed.

    account is the path from the annotated row to its Account, blank for an
    Account itself; a str as_of names the row's date field.
    """
    path = f"{account}__" if account else ""
    # The Splits' subquery reaches the row's date through OuterRef.
    on, day = (
        (models.OuterRef(as_of), models.F(as_of))
        if isinstance(as_of, str)
        else (as_of, as_of)
    )
    moved_in = _split_total("to_account", on, account=account or "pk") - (
        _split_total("from_account", on, account=account or "pk")
    )
    signed = models.Case(
        models.When(**{f"{path}kind": AccountKind.LIABILITY}, then=-moved_in),
        default=moved_in,
    )
    balance = models.F(f"{path}opening_balance") + signed
    if as_of is None:
        return balance
    return models.Case(
        models.When(**{f"{path}opening_balance_date__gt": day}, then=models.Value(0)),
        default=balance,
        output_field=MONEY,
    )


def _reconciliation_difference() -> models.Expression:
    """A Reconciliation's balance less its Account's Balance on its date now."""
    return models.F("balance") - _balance("date", account="account")


class AccountQuerySet(models.QuerySet["Account"]):
    """Queries over Accounts."""

    def with_balance(self, as_of: date | None = None) -> Self:
        """Annotate each Account's Balance; a Liability's reads as what is owed.

        With as_of, only Splits dated on or before it count, and an Account
        opening after it counts as 0.
        """
        return self.annotate(balance=_balance(as_of))

    def with_activity(self, name: str, since: date, until: date) -> Self:
        """Annotate how far each Account moved between the dates, inclusive.

        Positive is each kind's usual way: an Asset growing, a Liability owing
        more, an Expense spent or Income earned.
        """
        moved_in = _split_total("to_account", until, since) - _split_total(
            "from_account", until, since
        )
        signed = models.Case(
            models.When(kind__in=OWING_KINDS, then=-moved_in),
            default=moved_in,
        )
        return self.annotate(**{name: signed})

    def with_last_used(self) -> Self:
        """Annotate the date of each Account's newest Transaction, if any."""
        split = apps.get_model("transactions", "Split")
        newest = (
            split.objects.filter(
                models.Q(from_account=models.OuterRef("pk"))
                | models.Q(to_account=models.OuterRef("pk"))
            )
            .order_by("-transaction__date")
            .values("transaction__date")[:1]
        )
        return self.annotate(last_used=models.Subquery(newest))

    def with_latest_reconciliation(self) -> Self:
        """Annotate the date of each Account's latest Reconciliation, if any.

        off_by is how far that Reconciliation is off now; zero when it matches.
        """
        latest = (
            Reconciliation.objects.filter(account=models.OuterRef("pk"))
            .order_by("-date")
            .annotate(off=_reconciliation_difference())
        )
        return self.annotate(
            reconciled_on=models.Subquery(latest.values("date")[:1]),
            off_by=models.Subquery(latest.values("off")[:1]),
        )


CARD_SETTINGS_TOGETHER = (
    "Set the Statement Day, Due Day and Pays from Account together, "
    "or leave all three blank."
)


class Account(models.Model):
    """An Asset, Liability, Expense or Income Account; its kind never changes.

    Only Asset and Liability Accounts carry an Opening Balance and its date.
    """

    # Module-level so Meta's constraints can use BALANCE_KINDS built from it.
    Kind = AccountKind

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind)
    notes = models.TextField(blank=True)
    hidden = models.BooleanField(default=False)
    include_in_net_worth = models.BooleanField("Include in Net Worth", default=True)
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    opening_balance_date = models.DateField(null=True, blank=True)
    # Credit card settings, on Liability Accounts only: all three or none.
    statement_day = models.PositiveSmallIntegerField(
        "Statement Day",
        null=True,
        blank=True,
        validators=DAY_OF_MONTH,
        help_text="The day of the month the card's billing period closes.",
    )
    due_day = models.PositiveSmallIntegerField(
        "Due Day",
        null=True,
        blank=True,
        validators=DAY_OF_MONTH,
        help_text="The day of the month the Statement Amount must be paid by.",
    )
    pays_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cards_paid",
        limit_choices_to={"kind": AccountKind.ASSET},
        verbose_name="Pays from",
    )
    low_balance_threshold = models.DecimalField(
        "Low-Balance Threshold",
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text="Warn when the Forecast expects the Balance to fall below this.",
    )

    objects = AccountQuerySet.as_manager()
    history = HistoricalRecords()
    save_without_historical_record: Callable[..., None]
    # Set only on Accounts fetched through with_balance(), with_activity() as
    # the list names them, and with_last_used().
    balance: Decimal
    this_month: Decimal
    last_month: Decimal
    spent: Decimal
    last_used: date | None
    # Set only on Accounts fetched through with_latest_reconciliation().
    reconciled_on: date | None
    off_by: Decimal | None

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                Lower("name"), "kind", name="accounts_account_name_kind_ci_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=BALANCE_KINDS,
                    opening_balance__isnull=False,
                    opening_balance_date__isnull=False,
                )
                | (
                    ~models.Q(kind__in=BALANCE_KINDS)
                    & models.Q(
                        opening_balance__isnull=True,
                        opening_balance_date__isnull=True,
                    )
                ),
                name="accounts_account_opening_balance_by_kind",
                violation_error_message=(
                    "Only Asset and Liability Accounts have an Opening Balance "
                    "and date, and they need both."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind=AccountKind.LIABILITY,
                    statement_day__isnull=False,
                    due_day__isnull=False,
                    pays_from__isnull=False,
                )
                | models.Q(
                    statement_day__isnull=True,
                    due_day__isnull=True,
                    pays_from__isnull=True,
                ),
                name="accounts_account_card_settings_together",
                violation_error_message=CARD_SETTINGS_TOGETHER,
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def has_opening_balance(self) -> bool:
        """Whether this kind of Account carries an Opening Balance."""
        return self.kind in BALANCE_KINDS

    @property
    def owes(self) -> bool:
        """Whether its Balance is what is owed, so going up is bad."""
        return self.kind == AccountKind.LIABILITY

    @property
    def sign(self) -> int:
        """1 when money moving in grows this Account, -1 when it shrinks it."""
        return -1 if self.kind in OWING_KINDS else 1

    @property
    def past_threshold(self) -> bool:
        """Whether its Balance is past the Low-Balance Threshold now.

        Read like the Forecast's warning: a Liability's 0 means no warning.
        Needs the Balance from with_balance().
        """
        threshold = self.low_balance_threshold
        if self.owes:
            return bool(threshold) and self.balance > threshold
        return self.kind == AccountKind.ASSET and self.balance < threshold

    @property
    def is_card(self) -> bool:
        """Whether it has credit card settings."""
        return self.statement_day is not None

    def opens_after(self, when: date) -> bool:
        """Whether the date falls before this Account's Opening Balance date."""
        started = self.opening_balance_date
        return started is not None and when < started

    def balance_on(self, when: date) -> Decimal:
        """Its Balance at the end of the day, counting that day's Splits."""
        return Account.objects.with_balance(when).get(pk=self.pk).balance


class ReconciliationQuerySet(models.QuerySet["Reconciliation"]):
    """Queries over Reconciliations."""

    def with_difference(self) -> Self:
        """Annotate its balance less the Account's Balance on its date now.

        Zero means it still matches; nothing about matching is stored (ADR 0011).
        """
        return self.annotate(difference=_reconciliation_difference())

    def matching(self) -> Self:
        """Those whose balance still equals the Account's Balance on their date."""
        return self.with_difference().filter(difference=0)


class Reconciliation(models.Model):
    """The balance the bank said an Account held on a day, matched when recorded.

    Checked against the Balance whenever shown, never locked (ADR 0011). A
    Liability's balance reads as what is owed, like its Balance.
    """

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="reconciliations"
    )
    date = models.DateField()
    balance = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ReconciliationQuerySet.as_manager()
    # Set only on Reconciliations fetched through with_difference().
    difference: Decimal

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=("account", "date"),
                name="accounts_reconciliation_account_date_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.account} on {self.date}"
