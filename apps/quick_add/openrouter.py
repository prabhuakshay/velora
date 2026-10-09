"""The OpenRouter client: the only code that talks HTTP to OpenRouter.

Tests replace `complete` with a fake, so nothing else here needs faking.
"""

import json
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
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


def parsed(content: str) -> Any:  # noqa: ANN401
    """The content as JSON, or the raw text when it isn't JSON."""
    try:
        return json.loads(content)
    except ValueError:
        return content


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
    usage = data.get("usage") or {}
    return Reply(
        content=parsed(data["choices"][0]["message"]["content"]),
        model=data.get("model") or settings.OPENROUTER_MODEL,
        usage=Usage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cost=Decimal(str(usage.get("cost", 0))),
        ),
    )
