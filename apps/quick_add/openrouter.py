"""The OpenRouter client: the only code that talks HTTP to OpenRouter.

Tests replace `complete` with a fake, so nothing else here needs faking.
"""

import json
import math
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 60
MAX_TOKENS = 2000


@dataclass(frozen=True)
class Usage:
    """What one request used, from the reply's `usage`; cost is in USD."""

    prompt_tokens: int
    completion_tokens: int
    cost: Decimal


@dataclass(frozen=True)
class Reply:
    """The model's parsed JSON reply, the model that answered, and its usage."""

    content: Any
    model: str
    usage: Usage


def is_configured() -> bool:
    """Whether an API key is set; AI Quick Add is hidden without one."""
    return bool(settings.OPENROUTER_API_KEY)


def reply_content(data: dict[str, Any]) -> object:
    """The model's message content, or None when the response has none."""
    try:
        return data["choices"][0]["message"]["content"]
    except KeyError, IndexError, TypeError:
        return None


def parsed(content: object) -> Any:  # noqa: ANN401
    """The content as JSON, or as it came when it isn't JSON text."""
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except ValueError:
        return content


def count(value: object) -> int:
    """A token count from the reply, or 0 when it isn't one."""
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return int(value)
    return 0


def cost(value: object) -> Decimal:
    """The cost from the reply, or 0 when it isn't a number."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return Decimal(0)
    return amount if amount.is_finite() else Decimal(0)


def complete(messages: list[dict[str, str]], schema: dict[str, Any]) -> Reply:
    """Send the messages and get back a reply that follows the JSON schema.

    Raises urllib.error.URLError (HTTPError for non-2xx) on network failures,
    and ValueError when OpenRouter's response isn't the JSON it should be.
    Content the model sent that isn't JSON is returned as the raw text, so
    the request's usage is still known.
    """
    body = {
        "model": settings.OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "reasoning": {"effort": settings.OPENROUTER_REASONING_EFFORT},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "draft", "strict": True, "schema": schema},
        },
        "usage": {"include": True},
    }
    request = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "Velora",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        data = json.load(response)
    if not isinstance(data, dict):
        msg = "OpenRouter's response is not a JSON object."
        raise ValueError(msg)  # noqa: TRY004
    usage = data.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return Reply(
        content=parsed(reply_content(data)),
        model=data.get("model") or settings.OPENROUTER_MODEL,
        usage=Usage(
            prompt_tokens=count(usage.get("prompt_tokens")),
            completion_tokens=count(usage.get("completion_tokens")),
            cost=cost(usage.get("cost")),
        ),
    )
