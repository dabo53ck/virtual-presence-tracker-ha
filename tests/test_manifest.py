"""Tests for the integration manifest."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = (
    Path(__file__).parents[1]
    / "custom_components"
    / "virtual_presence_tracker"
    / "manifest.json"
)


def test_the_integration_is_listed_under_integrations() -> None:
    """The integration must not be a helper.

    Helpers are listed on the Helpers page, which has no way to add a config
    subentry, so a helper could never get a virtual tracker. Integrations with
    subentries (ollama, anthropic, telegram_bot, ...) are ``service``.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["integration_type"] == "service"
