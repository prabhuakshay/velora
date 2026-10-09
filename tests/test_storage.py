import importlib
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import storages

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


def load(monkeypatch: pytest.MonkeyPatch, **env: str) -> ModuleType:
    # Set even the blank ones: values in .env never override the process env.
    for name in config_settings.R2_ENV_VARS.values():
        monkeypatch.setenv(name, env.get(name, ""))
    return importlib.reload(config_settings)


def test_attachments_go_to_the_r2_bucket_from_env_with_short_lived_links(
    monkeypatch: pytest.MonkeyPatch, reloaded_settings: ModuleType
) -> None:
    loaded = load(
        monkeypatch,
        R2_ENDPOINT_URL="https://account.r2.cloudflarestorage.com",
        R2_BUCKET_NAME="velora-test",
        R2_ACCESS_KEY_ID="test-key",
        R2_SECRET_ACCESS_KEY="test-secret",
    )

    storage = storages.create_storage(loaded.STORAGES["default"])
    link = urlsplit(storage.url("attachments/0123abcd"))

    assert f"{link.scheme}://{link.netloc}{link.path}" == (
        "https://account.r2.cloudflarestorage.com/velora-test/attachments/0123abcd"
    )
    query = parse_qs(link.query)
    assert query["X-Amz-Credential"][0].startswith("test-key/")
    assert query["X-Amz-Expires"] == ["300"]


def test_image_previews_may_load_from_the_r2_endpoint(
    monkeypatch: pytest.MonkeyPatch, reloaded_settings: ModuleType
) -> None:
    loaded = load(
        monkeypatch, R2_ENDPOINT_URL="https://account.r2.cloudflarestorage.com"
    )

    assert "https://account.r2.cloudflarestorage.com" in loaded.SECURE_CSP["img-src"]


def test_missing_r2_settings_fail_clearly_once_storage_is_used(
    monkeypatch: pytest.MonkeyPatch, reloaded_settings: ModuleType
) -> None:
    loaded = load(monkeypatch, R2_BUCKET_NAME="velora-test")

    with pytest.raises(ImproperlyConfigured) as error:
        storages.create_storage(loaded.STORAGES["default"])

    assert str(error.value) == (
        "Attachment storage needs R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, "
        "R2_SECRET_ACCESS_KEY to be set."
    )
