"""Turn a Quick Add into a Draft by asking the AI."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.quick_add import openrouter
from apps.quick_add.models import AICall, Draft, DraftSplit, QuickAdd

NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_INTEGER = {"type": ["integer", "null"]}

# Strict structured output needs every property required and no extras;
# optional fields are nullable instead.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["date", "party_id", "new_party_name", "description", "splits"],
    "properties": {
        "date": NULLABLE_STRING | {"description": "YYYY-MM-DD"},
        "party_id": NULLABLE_INTEGER,
        "new_party_name": NULLABLE_STRING,
        "description": NULLABLE_STRING,
        "splits": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from_account_id", "to_account_id", "amount"],
                "properties": {
                    "from_account_id": {"type": "integer"},
                    "to_account_id": {"type": "integer"},
                    "amount": {
                        "type": "string",
                        "description": "Rupees with up to 2 decimals, e.g. 850.00",
                    },
                },
            },
        },
    },
}

INSTRUCTIONS = """\
You turn a short note about one money event into a proposed Transaction for a \
personal finance app. All amounts are in Indian rupees.

A Transaction has a date, optionally a Party, optionally a description, and \
1 to 10 Splits. Each Split moves a positive amount from one Account to a \
different Account. All Splits share the same from-Account or the same \
to-Account.

Account kinds: asset (bank, cash, money lent), liability (credit card, loan), \
expense (what money is spent on), income (where earned money comes from). \
Spending moves money from an asset or liability to an expense; earning moves \
it from an income to an asset; a transfer moves it between assets and \
liabilities.

Rules:
- Use only the Account IDs listed below. Never invent Accounts.
- date: the date the note refers to, as YYYY-MM-DD, worked out relative to \
the date it was written ("yesterday", "on the 3rd"). Null if the note gives none.
- party_id: the ID of a listed Party the note refers to, even if written \
loosely. new_party_name: a name for a Party that isn't listed. Never both; \
both null if the note names no one.
- description: at most 200 characters, only when the Party and Accounts \
don't already say what happened; otherwise null.
"""


def written_on(quick_add: QuickAdd) -> date:
    """The day the user wrote the Quick Add, in the app's time zone."""
    return timezone.localdate(quick_add.created_at)


def build_messages(quick_add: QuickAdd) -> list[dict[str, str]]:
    """The prompt: instructions, active Accounts and Parties, and the note."""
    context = {
        "written_on": written_on(quick_add).isoformat(),
        "accounts": list(
            Account.objects.filter(hidden=False)
            .order_by("pk")
            .values("id", "name", "kind")
        ),
        "parties": list(
            Party.objects.filter(hidden=False).order_by("pk").values("id", "name")
        ),
    }
    return [
        {"role": "system", "content": INSTRUCTIONS + "\n" + json.dumps(context)},
        {"role": "user", "content": quick_add.text},
    ]


def ask_ai(quick_add: QuickAdd) -> tuple[openrouter.Reply, AICall]:
    """Send one request for the Quick Add and record what it cost."""
    reply = openrouter.complete(build_messages(quick_add), SCHEMA)
    call = AICall.objects.create(
        quick_add=quick_add,
        model=reply.model,
        prompt_tokens=reply.usage.prompt_tokens,
        completion_tokens=reply.usage.completion_tokens,
        cost=reply.usage.cost,
    )
    return reply, call


@transaction.atomic
def save_draft(quick_add: QuickAdd, content: dict[str, Any]) -> Draft:
    """Store the reply as the Quick Add's Draft and mark it `draft`."""
    draft = Draft.objects.create(
        quick_add=quick_add,
        date=date.fromisoformat(content["date"])
        if content["date"]
        else written_on(quick_add),
        party_id=content["party_id"],
        new_party_name=content["new_party_name"] or "",
        description=content["description"] or "",
    )
    DraftSplit.objects.bulk_create(
        DraftSplit(
            draft=draft,
            from_account_id=split["from_account_id"],
            to_account_id=split["to_account_id"],
            amount=Decimal(split["amount"]),
        )
        for split in content["splits"]
    )
    quick_add.status = QuickAdd.Status.DRAFT
    quick_add.save(update_fields=["status"])
    return draft


def draft_quick_add(quick_add: QuickAdd) -> None:
    """Ask the AI for a Draft of the Quick Add and save it."""
    reply, call = ask_ai(quick_add)
    save_draft(quick_add, reply.content)
    call.succeeded = True
    call.save(update_fields=["succeeded"])
