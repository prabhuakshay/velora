import importlib
from typing import TYPE_CHECKING

import environ
import pytest

from config import settings as config_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


@pytest.fixture
def reloaded_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """config.settings re-read under the env the test sets up."""
    yield config_settings
    monkeypatch.undo()
    importlib.reload(config_settings)


def test_time_zone_defaults_to_india_when_unset(
    monkeypatch: pytest.MonkeyPatch, reloaded_settings: ModuleType
) -> None:
    # A local .env may set TIME_ZONE; ignore it so only the default is left.
    monkeypatch.setattr(environ.Env, "read_env", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("TIME_ZONE", raising=False)

    assert importlib.reload(reloaded_settings).TIME_ZONE == "Asia/Kolkata"
