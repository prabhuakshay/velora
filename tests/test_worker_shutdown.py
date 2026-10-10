import re
from pathlib import Path

from apps.quick_add import openrouter

COMPOSE = Path(__file__).resolve().parent.parent / "compose.prod.yaml"


def test_the_worker_may_finish_an_ai_call_before_it_is_killed() -> None:
    worker = COMPOSE.read_text().split("\n  worker:\n", 1)[1]
    grace = re.search(r"stop_grace_period: (\d+)s", worker)

    assert grace
    assert int(grace[1]) > openrouter.TIMEOUT_SECONDS
