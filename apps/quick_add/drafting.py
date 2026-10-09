"""Turn a Quick Add into a Draft by asking the AI."""

import json
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.quick_add import openrouter, validation
from apps.quick_add.models import AICall, Draft, DraftSplit, QuickAdd

# An invalid reply gets one more try, with its errors fed back.
INVALID_REPLY_TRIES = 2

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
You turn a Quick Add, a short free-text line about one money event, into a \
proposed Transaction for a personal finance app. All amounts are in Indian \
rupees.

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
- date: the date the Quick Add refers to, as YYYY-MM-DD, worked out relative to \
the date it was written ("yesterday", "on the 3rd"). Null if the Quick Add gives none.
- party_id: the ID of a listed Party the Quick Add refers to, even if written \
loosely. new_party_name: a name for a Party that isn't listed. Never both; \
both null if the Quick Add names no one.
- description: at most 200 characters, only when the Party and Accounts \
don't already say what happened; otherwise null.
"""


def written_on(quick_add: QuickAdd) -> date:
    """The day the user wrote the Quick Add, in the app's time zone."""
    return timezone.localdate(quick_add.created_at)


def build_messages(quick_add: QuickAdd) -> list[dict[str, str]]:
    """The prompt: instructions, active Accounts and Parties, and the Quick Add text."""
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


def ask_ai(
    quick_add: QuickAdd, messages: list[dict[str, str]]
) -> tuple[openrouter.Reply, AICall]:
    """Send one request for the Quick Add and record what it cost.

    A request that fails is still recorded, with no usage.
    """
    try:
        reply = openrouter.complete(messages, SCHEMA)
    except Exception as error:
        AICall.objects.create(quick_add=quick_add, model=settings.OPENROUTER_MODEL)
        if isinstance(error, HTTPError):
            # It holds the open error response; only its status code is needed.
            error.close()
        raise
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
            amount=Decimal(str(split["amount"])),
        )
        for split in content["splits"]
    )
    quick_add.status = QuickAdd.Status.DRAFT
    quick_add.failure_reason = ""
    quick_add.save(update_fields=["status", "failure_reason"])
    return draft


class TransientError(Exception):
    """OpenRouter couldn't be reached or failed on its side; worth retrying."""


def fail(quick_add: QuickAdd, reason: str) -> None:
    """Mark the Quick Add failed, with a reason the user can read."""
    quick_add.status = QuickAdd.Status.FAILED
    quick_add.failure_reason = reason
    quick_add.save(update_fields=["status", "failure_reason"])


def request_failure(error: OSError) -> str | None:
    """Why the request failed, or None when it is worth retrying."""
    if isinstance(error, HTTPError) and error.code < HTTPStatus.INTERNAL_SERVER_ERROR:
        return f"OpenRouter refused the request (HTTP {error.code})."
    return None


def feedback(content: object, errors: list[str]) -> list[dict[str, str]]:
    """The AI's invalid reply and why, so its next try can correct it."""
    return [
        {"role": "assistant", "content": json.dumps(content)},
        {
            "role": "user",
            "content": "That reply broke these rules; send a corrected one.\n"
            + "\n".join(f"- {error}" for error in errors),
        },
    ]


def draft_quick_add(quick_add: QuickAdd, *, last_attempt: bool = True) -> None:
    """Ask the AI for a Draft of the Quick Add and save it, or mark it failed.

    An invalid reply is asked again once, with the errors fed back. A network
    or server failure raises TransientError for the job to be retried, unless
    this is the job's last attempt or the failed request was that corrective
    retry: retrying the job would start over and spend the one retry again.
    """
    messages = build_messages(quick_add)
    errors: list[str] = []
    for _ in range(INVALID_REPLY_TRIES):
        try:
            reply, call = ask_ai(quick_add, messages)
        except ValueError:
            errors = ["The reply was not valid JSON."]
            continue
        except OSError as error:
            if reason := request_failure(error):
                fail(quick_add, reason)
                return
            if errors:
                break
            if not last_attempt:
                raise TransientError from error
            fail(quick_add, "Couldn't reach OpenRouter; try again later.")
            return
        errors = validation.reply_errors(reply.content, written_on(quick_add))
        if not errors:
            save_draft(quick_add, reply.content)
            call.succeeded = True
            call.save(update_fields=["succeeded"])
            return
        messages = [*messages, *feedback(reply.content, errors)]
    fail(quick_add, "The AI's reply was invalid: " + " ".join(errors))
