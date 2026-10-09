"""Server-side checks of an AI reply before it may become a Draft.

The schema sent to the AI asks for the same shape, but nothing guarantees
the model follows it, so every rule is checked here again.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.quick_add.models import PARTY_NAME_MAX_LENGTH
from apps.transactions.forms import direction_error

FIELDS = {"date", "party_id", "new_party_name", "description", "splits"}
SPLIT_FIELDS = {"from_account_id", "to_account_id", "amount"}
MAX_SPLITS = 10
MAX_AMOUNT = Decimal(10_000_000)
MAX_DECIMALS = 2
MAX_DESCRIPTION = 200


def reply_errors(content: object, written: date) -> list[str]:
    """Why the reply cannot become a Draft; empty when it can.

    `written` is the day the Quick Add was written, which the date defaults to.
    """
    if errors := _shape_errors(content, FIELDS, "The reply"):
        return errors
    assert isinstance(content, dict)  # noqa: S101
    when, errors = _date_errors(content["date"], written)
    return errors + _party_errors(content) + _splits_errors(content["splits"], when)


def _shape_errors(fields: object, expected: set[str], where: str) -> list[str]:
    if not isinstance(fields, dict):
        return [f"{where} must be a JSON object."]
    unknown = [
        f"Unknown field '{name}' in {where}." for name in fields.keys() - expected
    ]
    missing = [
        f"Missing field '{name}' in {where}." for name in expected - fields.keys()
    ]
    return sorted(unknown) + sorted(missing)


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text_errors(value: object, what: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        return [f"{what} must be text."]
    return [f"{what} can be at most {limit} characters."] if len(value) > limit else []


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None


def _year_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def _date_errors(value: object, written: date) -> tuple[date | None, list[str]]:
    if value is None:
        return written, []
    when = _parse_date(value)
    if when is None:
        return None, [f"The date '{value}' is not a YYYY-MM-DD date."]
    rules = [
        (when > timezone.localdate(), "The date cannot be after today."),
        (
            when < _year_before(written),
            "The date cannot be more than 1 year before the Quick Add.",
        ),
    ]
    return when, [message for broken, message in rules if broken]


def _parse_amount(value: object) -> Decimal | None:
    if not isinstance(value, str | int) or isinstance(value, bool):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _amount_errors(value: object, where: str) -> list[str]:
    amount = _parse_amount(value)
    if amount is None:
        return [f"{where}: the amount '{value}' is not a number."]
    rules = [
        (amount <= 0, "must be greater than zero"),
        (amount > MAX_AMOUNT, "cannot be above ₹1,00,00,000"),
        (
            -int(amount.as_tuple().exponent) > MAX_DECIMALS,
            "can have at most 2 decimals",
        ),
    ]
    return [f"{where}: the amount {message}." for broken, message in rules if broken]


def _party_errors(content: dict[str, Any]) -> list[str]:
    party_id, name = content["party_id"], content["new_party_name"]
    errors = []
    if party_id is not None and not (
        _is_id(party_id) and Party.objects.filter(pk=party_id, hidden=False).exists()
    ):
        errors.append(f"Party {party_id} is unknown.")
    errors += _text_errors(name, "The new Party name", PARTY_NAME_MAX_LENGTH)
    if party_id is not None and name:
        errors.append("Give a Party ID or a new Party name, not both.")
    errors += _text_errors(content["description"], "The description", MAX_DESCRIPTION)
    return errors


def _account_errors(
    pk: object, account: Account | None, when: date | None, where: str
) -> list[str]:
    if account is None:
        return [f"{where}: Account {pk} is unknown or inactive."]
    if when and account.opens_after(when):
        started = date_format(account.opening_balance_date, "j M Y")  # type: ignore[arg-type]
        return [
            (
                f"{where}: the date cannot be before the Opening Balance date of "
                f"{account} ({started})."
            )
        ]
    return []


def _split_errors(
    split: dict[str, Any], accounts: dict[Any, Account], when: date | None, where: str
) -> list[str]:
    source_id, destination_id = split["from_account_id"], split["to_account_id"]
    source = accounts.get(source_id) if _is_id(source_id) else None
    destination = accounts.get(destination_id) if _is_id(destination_id) else None
    errors = [
        *_amount_errors(split["amount"], where),
        *_account_errors(source_id, source, when, where),
        *_account_errors(destination_id, destination, when, where),
    ]
    if source is None or destination is None:
        return errors
    if source == destination:
        errors.append(f"{where}: a Split cannot go from an Account to itself.")
    elif error := direction_error(source, destination):
        errors.append(f"{where}: {error}")
    return errors


def _splits_errors(splits: object, when: date | None) -> list[str]:
    if not isinstance(splits, list) or not 1 <= len(splits) <= MAX_SPLITS:
        return [f"There must be 1 to {MAX_SPLITS} Splits."]
    errors = []
    for number, split in enumerate(splits, start=1):
        errors += _shape_errors(split, SPLIT_FIELDS, f"Split {number}")
    if errors:
        return errors
    ids = [
        split[key] for split in splits for key in ("from_account_id", "to_account_id")
    ]
    accounts = Account.objects.filter(
        pk__in=[pk for pk in ids if _is_id(pk)], hidden=False
    ).in_bulk()
    for number, split in enumerate(splits, start=1):
        errors += _split_errors(split, accounts, when, f"Split {number}")
    sources = {str(split["from_account_id"]) for split in splits}
    destinations = {str(split["to_account_id"]) for split in splits}
    if len(sources) > 1 and len(destinations) > 1:
        errors.append("Splits must share a From or a To Account.")
    return errors
