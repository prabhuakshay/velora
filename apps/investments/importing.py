"""Investment Import: check a CSV in full, then apply it all or nothing (ADR 0013).

Each row goes through InvestmentEventForm, the same as an event recorded by
hand, so the checks (such as overselling) and the ledger links are the same.
Rows apply in date order inside one database transaction; a preview rolls
it back, so later rows are checked against the earlier ones without anything
changing until the import is confirmed.
"""

import csv
import datetime
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from django.core.exceptions import NON_FIELD_ERRORS
from django.db import transaction as db_transaction

from apps.accounts.models import Account
from apps.investments.drafts import save_investment
from apps.investments.export import COLUMNS
from apps.investments.forms import InvestmentEventForm
from apps.investments.ledger import moves_ledger_money
from apps.investments.matching import matching_transaction
from apps.investments.models import DraftInvestment, Instrument, InvestmentEvent
from apps.investments.replay import DAY_ORDER, MERGER, TRADES
from apps.investments.trade_price import agrees, trade_price
from apps.quick_add.models import Draft

if TYPE_CHECKING:
    from apps.transactions.models import Transaction

TYPES = {kind.upper(): kind for kind in DAY_ORDER}
# Form fields named differently from their column; the Income Account a
# Dividend comes from is taken from its matched Transaction instead.
COLUMN_OF = {"kind": "type"}
HIDDEN_ERRORS = {"income_account"}
REF_LENGTH = int(InvestmentEvent._meta.get_field("ref").max_length or 0)
ISIN_LENGTH = int(Instrument._meta.get_field("isin").max_length or 0)
NAME_LENGTH = int(Instrument._meta.get_field("name").max_length or 0)


@dataclass
class ImportRow:
    """One row of the file and what the import makes of it.

    A row that moves ledger money after its account's Opening Balance date
    needs a Transaction: the recorded one it matched, or None when unmatched,
    in which case the row becomes a Draft to review and post (ADR 0006).
    """

    line: int
    values: dict[str, str]
    errors: list[str] = field(default_factory=list)
    duplicate: bool = False
    needs_transaction: bool = False
    transaction: Transaction | None = None

    @property
    def unmatched(self) -> bool:
        """Whether it needs a Transaction and none was recorded."""
        return self.needs_transaction and self.transaction is None

    @property
    def units(self) -> Decimal | None:
        """The row's units as a number, or None when blank or unreadable."""
        return _decimal(self.values["units"])

    @property
    def amount(self) -> Decimal | None:
        """The row's amount as a number, or None when blank or unreadable."""
        return _decimal(self.values["amount"])


@dataclass
class ImportResult:
    """Every row's outcome, or why the file can't be read at all."""

    rows: list[ImportRow] = field(default_factory=list)
    problem: str = ""

    @property
    def errors(self) -> list[ImportRow]:
        """Rows that block the import."""
        return [row for row in self.rows if row.errors]

    @property
    def duplicates(self) -> list[ImportRow]:
        """Rows already recorded, which the import skips."""
        return [row for row in self.rows if row.duplicate and not row.errors]

    @property
    def valid(self) -> list[ImportRow]:
        """Rows the import adds, as Investment Events or Drafts."""
        return [row for row in self.rows if not row.duplicate and not row.errors]

    @property
    def drafts(self) -> list[ImportRow]:
        """Rows the import proposes as Drafts."""
        return [row for row in self.valid if row.unmatched]

    @property
    def can_confirm(self) -> bool:
        """Whether nothing blocks applying it."""
        return not self.problem and not self.errors


def check(text: str) -> ImportResult:
    """What importing the file would do, changing nothing."""
    with db_transaction.atomic():
        result = _run(text)
        db_transaction.set_rollback(True)
    return result


def apply(text: str) -> ImportResult:
    """Import the file if nothing blocks it; otherwise change nothing."""
    with db_transaction.atomic():
        result = _run(text)
        if not result.can_confirm:
            db_transaction.set_rollback(True)
    return result


def _run(text: str) -> ImportResult:
    result = _read(text)
    for row in sorted(result.rows, key=_order):
        _import(row)
    return result


def _read(text: str) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip().lower() for name in reader.fieldnames or []]
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        return ImportResult(problem=f"Missing columns: {', '.join(missing)}.")
    reader.fieldnames = header
    rows = [
        ImportRow(
            line=reader.line_num,
            values={column: (raw.get(column) or "").strip() for column in COLUMNS},
        )
        for raw in reader
    ]
    return ImportResult(rows=rows, problem="" if rows else "The file has no rows.")


def _date(text: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _decimal(text: str) -> Decimal | None:
    try:
        number = Decimal(text) if text else None
    except InvalidOperation:
        return None
    return number if number is not None and number.is_finite() else None


def _order(row: ImportRow) -> tuple[datetime.date, int, int]:
    # Same-day events apply in replay's day order, so a Sell follows its Buy.
    kind = TYPES.get(row.values["type"].upper())
    return (
        _date(row.values["date"]) or datetime.date.max,
        DAY_ORDER.index(kind) if kind else len(DAY_ORDER),
        row.line,
    )


def _parts(row: ImportRow) -> tuple[Account, str, datetime.date] | None:
    values = row.values
    when = _date(values["date"])
    kind = TYPES.get(values["type"].upper())
    account = (
        Account.objects.investment().filter(name__iexact=values["account"]).first()
    )
    if when is None:
        row.errors.append("date: Use a date like 2026-03-31.")
    if kind is None:
        row.errors.append(f"type: Use one of {', '.join(TYPES)}.")
    if account is None:
        row.errors.append(
            f"account: No Investment Account is named “{values['account']}”."
        )
    if len(values["ref"]) > REF_LENGTH:
        row.errors.append(f"ref: Keep it to {REF_LENGTH} characters.")
    if row.errors or account is None or kind is None or when is None:
        return None
    return account, kind, when


def _recorded(row: ImportRow, account: Account, kind: str, when: datetime.date) -> bool:
    """Whether the row is an Investment Event already, or a Draft waiting to be."""
    values = row.values
    drafts = DraftInvestment.objects.filter(draft__status=Draft.Status.WAITING)
    if values["ref"]:
        return (
            InvestmentEvent.objects.filter(ref=values["ref"]).exists()
            or drafts.filter(ref=values["ref"]).exists()
        )
    same = {
        "account": account,
        "kind": kind,
        "instrument__isin": values["isin"].upper(),
        "units": _decimal(values["units"]),
        "amount": _decimal(values["amount"]),
    }
    return (
        InvestmentEvent.objects.filter(date=when, **same).exists()
        or drafts.filter(draft__date=when, **same).exists()
    )


def _import(row: ImportRow) -> None:
    parts = _parts(row)
    if parts is None:
        return
    account, kind, when = parts
    if _recorded(row, account, kind, when):
        row.duplicate = True
        return
    values = row.values
    event = InvestmentEvent(
        account=account,
        kind=kind,
        date=when,
        amount=_decimal(values["amount"]),
        charges=_decimal(values["charges"]) or Decimal(0),
    )
    if event.amount is not None and moves_ledger_money(event):
        row.needs_transaction = True
        row.transaction = matching_transaction(event)
    if kind == MERGER:
        _define_merger_target(values)
    form = InvestmentEventForm(
        _form_data(values, kind),
        account=account,
        matched=row.transaction,
        drafting=row.unmatched,
        instance=InvestmentEvent(ref=values["ref"]),
    )
    if not form.is_valid():
        row.errors.extend(_messages(form))
    _check_stated_price(row, kind)
    if row.errors:
        return
    if row.unmatched:
        _propose_draft(form)
    else:
        form.save()


def _check_stated_price(row: ImportRow, kind: str) -> None:
    """Refuse a stated price that disagrees with the units and amount.

    The price is optional and never stored: the Trade Price comes from the
    units and amount (ADR 0016), so this only catches a typo in either.
    """
    text = row.values["price"]
    if not text or kind not in TRADES:
        return
    price = _decimal(text)
    if price is None:
        row.errors.append("price: Enter a number.")
        return
    units, amount = row.units, row.amount
    if units is None or amount is None:
        return
    expected = trade_price(units, amount)
    if expected is not None and not agrees(units, price, amount):
        row.errors.append(
            f"price: Doesn't agree with units and amount, which give {expected}."
        )


def _propose_draft(form: InvestmentEventForm) -> None:
    """Save the checked event as a Draft carrying it, to post once reviewed."""
    event = form.save(commit=False)
    if form.new_instrument is not None:
        event.instrument.save()
    draft = Draft.objects.create(
        source=Draft.Source.INVESTMENT_IMPORT,
        date=event.date,
        description=f"{event.get_kind_display()} {event.instrument}",
    )
    save_investment(
        DraftInvestment(
            draft=draft,
            account=event.account,
            instrument=event.instrument,
            kind=event.kind,
            units=event.units,
            amount=event.amount,
            charges=event.charges,
            ref=event.ref,
            note=event.note,
        )
    )


def _define_merger_target(values: dict[str, str]) -> None:
    """Create a Merger's unknown new Instrument, named by the row.

    A Merger's old Instrument is already held, so its instrument_name is free
    to name the new one.
    """
    isin = values["new_isin"].upper()
    name = values["instrument_name"]
    if (
        name
        and 0 < len(isin) <= ISIN_LENGTH
        and len(name) <= NAME_LENGTH
        and not Instrument.objects.filter(isin=isin).exists()
    ):
        Instrument.objects.create(isin=isin, name=name, kind=Instrument.Kind.STOCK)


def _form_data(values: dict[str, str], kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "date": values["date"],
        "isin": values["isin"],
        "instrument_name": "" if kind == MERGER else values["instrument_name"],
        "units": values["units"],
        "amount": values["amount"],
        "charges": values["charges"] or "0",
        "new_isin": values["new_isin"],
        "note": values["note"],
    }


def _messages(form: InvestmentEventForm) -> list[str]:
    return [
        str(message)
        if name == NON_FIELD_ERRORS
        else f"{COLUMN_OF.get(name, name)}: {message}"
        for name, messages in form.errors.items()
        if name not in HIDDEN_ERRORS
        for message in messages
    ]
