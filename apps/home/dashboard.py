"""What the home dashboard sums up: Net Worth, money in and out, cards and more."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Prefetch, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse

from apps.accounts.activity import month_end
from apps.accounts.models import Account, AccountKind
from apps.accounts.net_worth import history_dates, net_worth_on
from apps.cards.models import Statement
from apps.classification.models import earned, spent
from apps.core.dates import month_start, months_after
from apps.home.charts import Bar, Line, bar, line
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from apps.accounts.net_worth import NetWorth
    from apps.budgets.picture import BudgetPicture, BudgetRow, Row

# Months of history each Net Worth range shows; None is all of it.
RANGES = {"6m": 6, "1y": 12, "all": None}
DEFAULT_RANGE = "1y"
CASH_FLOW_MONTHS = 12
SPENDING_SHOWN = 5
RECENT_SHOWN = 6
BUDGETS_SHOWN = 5
# Categorical slots in a fixed order, so an Expense Account keeps its colour
# only within one month's ranking; Other is always the neutral last slot.
SLOT_CLASSES = (
    "fill-[#2a78d6]",
    "fill-[#eb6834]",
    "fill-[#1baf7a]",
    "fill-[#eda100]",
    "fill-[#e87ba4]",
)
OTHER_CLASS = "fill-slate-300"


@dataclass(frozen=True)
class NetWorthCard:
    """Net Worth now, how far it moved since last month-end, and its history."""

    now: NetWorth
    change: Decimal
    since: date
    history: list[tuple[date, Decimal]]
    chart: Line | None

    @property
    def change_percent(self) -> Decimal | None:
        """The change as a share of last month-end's Net Worth."""
        before = self.now.total - self.change
        if not before:
            return None
        return round(self.change / abs(before) * 100, 1)


def net_worth_card(today: date, months: int | None, *, charted: bool) -> NetWorthCard:
    """Net Worth with its history over the last months, uncharted in Privacy Mode."""
    since = month_start(today) - timedelta(days=1)
    points: list[date] = []
    if charted:
        start = None if months is None else months_after(since, -months)
        points = history_dates(today, start)
    values = net_worth_on([since, *points, today])
    now = values[today]
    history = [(when, values[when].total) for when in points]
    return NetWorthCard(
        now=now,
        change=now.total - values[since].total,
        since=since,
        history=history,
        chart=line([value for _, value in history]) if len(history) > 1 else None,
    )


@dataclass(frozen=True)
class MonthFlow:
    """One calendar month's money earned and spent; Transfers count in neither."""

    start: date
    earned: Decimal
    spent: Decimal

    @property
    def saved(self) -> Decimal:
        """What was earned and not spent; negative when spending ran over."""
        return self.earned - self.spent

    @property
    def savings_rate(self) -> int | None:
        """The share of earnings kept, None with nothing earned."""
        return round(self.saved / self.earned * 100) if self.earned > 0 else None


def cash_flow(today: date, count: int = CASH_FLOW_MONTHS) -> list[MonthFlow]:
    """The last count months up to today's, oldest first."""
    first = months_after(month_start(today), 1 - count)
    totals = {
        month: (money_in, money_out)
        for month, money_in, money_out in Split.objects.filter(
            transaction__date__range=(first, month_end(month_start(today)))
        )
        .annotate(month=TruncMonth("transaction__date"))
        .order_by()
        .values("month")
        .annotate(
            money_in=Sum(earned(), default=Decimal(0)),
            money_out=Sum(spent(), default=Decimal(0)),
        )
        .values_list("month", "money_in", "money_out")
    }
    months = (months_after(first, offset) for offset in range(count))
    return [
        MonthFlow(start, *totals.get(start, (Decimal(0), Decimal(0))))
        for start in months
    ]


def spent_between(start: date, end: date) -> Decimal:
    """What was spent between the dates, inclusive, less Refunds."""
    total: Decimal = Split.objects.filter(
        transaction__date__range=(start, end)
    ).aggregate(total=Sum(spent(), default=Decimal(0)))["total"]
    return total


def spent_by_now_last_month(today: date) -> Decimal:
    """What last month had spent by the same day of the month as today."""
    start = months_after(month_start(today), -1)
    return spent_between(start, months_after(today, -1))


@dataclass(frozen=True)
class Slice:
    """One Expense Account's part of a month's spending, for the stacked bar."""

    name: str
    url: str
    total: Decimal
    last_month: Decimal
    percent: float
    x: float
    fill: str


def spending(today: date) -> list[Slice]:
    """This month's biggest Expense Accounts, then the rest as Other."""
    this_month = month_start(today)
    last_month = months_after(this_month, -1)
    accounts = sorted(
        (
            account
            for account in Account.objects.filter(kind=AccountKind.EXPENSE)
            .with_activity("this_month", this_month, month_end(this_month))
            .with_activity("last_month", last_month, month_end(last_month))
            if account.this_month > 0
        ),
        key=lambda account: (-account.this_month, account.name.lower()),
    )
    whole = sum((account.this_month for account in accounts), Decimal(0))
    rows = [
        (
            account.name,
            reverse("account_transactions", args=[account.kind, account.pk]),
            account.this_month,
            account.last_month,
            SLOT_CLASSES[index],
        )
        for index, account in enumerate(accounts[:SPENDING_SHOWN])
    ]
    if rest := accounts[SPENDING_SHOWN:]:
        rows.append(
            (
                f"{len(rest)} more",
                "",
                sum((account.this_month for account in rest), Decimal(0)),
                sum((account.last_month for account in rest), Decimal(0)),
                OTHER_CLASS,
            )
        )
    slices = []
    x = 0.0
    for name, url, total, before, fill in rows:
        percent = float(total / whole * 100)
        slices.append(Slice(name, url, total, before, percent, x, fill))
        x += percent
    return slices


@dataclass(frozen=True)
class CardRow:
    """A credit card: what it owes, its limit and its latest Statement."""

    card: Account
    statement: Statement | None

    @property
    def limit_percent(self) -> int | None:
        """How much of the Low-Balance Threshold, as a limit, is used."""
        limit = self.card.low_balance_threshold
        if not limit:
            return None
        return min(max(round(self.card.balance / limit * 100), 0), 100)


def cards(today: date) -> list[CardRow]:
    """Each visible credit card with its latest closed Statement."""
    accounts = list(
        Account.objects.filter(
            kind=AccountKind.LIABILITY, hidden=False, statement_day__isnull=False
        )
        .with_balance()
        .order_by("name")
    )
    latest = {
        statement.card_id: statement
        for statement in Statement.objects.filter(
            card__in=accounts, period_end__lte=today
        )
        .order_by("card_id", "-period_end")
        .distinct("card_id")
    }
    return [CardRow(card, latest.get(card.pk)) for card in accounts]


@dataclass(frozen=True)
class BudgetCard:
    """This month's Budgets, what needs attention first."""

    overall: Row | None
    rows: list[BudgetRow]
    more: int


def budget_card(picture: BudgetPicture) -> BudgetCard | None:
    """The Overall Budget, then Budgets over, close, then by share Spent.

    None when no Budget or Overall Budget applies that month.
    """
    if not picture.rows and picture.overall is None:
        return None
    rows = picture.by_attention
    return BudgetCard(picture.overall, rows[:BUDGETS_SHOWN], len(rows[BUDGETS_SHOWN:]))


def recent_transactions(count: int = RECENT_SHOWN) -> list[Transaction]:
    """The newest Transactions, with what the list shows of each."""
    return list(
        Transaction.objects.select_related("party")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=Split.objects.select_related("from_account", "to_account"),
            )
        )
        .annotate(total=Sum("splits__amount"))
        .order_by("-date", "-pk")[:count]
    )


@dataclass(frozen=True)
class FlowColumn:
    """One month's pair of bars: money earned beside money spent."""

    month: MonthFlow
    earned: Bar
    spent: Bar
    current: bool


def flow_columns(flows: list[MonthFlow]) -> list[FlowColumn]:
    """Each month's bars, scaled so the biggest month fills the chart."""
    peak = max((max(f.earned, f.spent) for f in flows), default=Decimal(0))
    return [
        FlowColumn(
            flow, bar(flow.earned, peak), bar(flow.spent, peak), flow is flows[-1]
        )
        for flow in flows
    ]
