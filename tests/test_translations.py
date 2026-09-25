"""Tests for the strings, the translations and the icons.

Home Assistant reads `translations/en.json`, never `strings.json`, so a string
that is only added to one of the two is invisible in the UI - and a key that
only exists in English leaves a German instance with a blank label.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

COMPONENT = Path(__file__).parents[1] / "custom_components" / "virtual_presence_tracker"
TRANSLATIONS = COMPONENT / "translations"


def load(path: Path) -> dict[str, Any]:
    """Return the contents of one JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def keys(value: Any, prefix: str = "") -> set[str]:
    """Return every key of a nested mapping, as dotted paths."""
    if not isinstance(value, dict):
        return set()
    return {prefix + key for key in value} | {
        path for key, item in value.items() for path in keys(item, f"{prefix}{key}.")
    }


def test_english_is_a_copy_of_the_strings() -> None:
    """`translations/en.json` is `strings.json`, byte for byte."""
    assert (TRANSLATIONS / "en.json").read_bytes() == (
        COMPONENT / "strings.json"
    ).read_bytes()


@pytest.mark.parametrize("language", ["de", "fr", "es"])
def test_a_translation_has_every_key(language: str) -> None:
    """A translation has the keys of the strings, and no others."""
    expected = keys(load(COMPONENT / "strings.json"))
    actual = keys(load(TRANSLATIONS / f"{language}.json"))

    assert actual == expected


def test_every_entity_has_a_name_and_an_icon() -> None:
    """Every entity of the integration is named and has an icon of its own."""
    entities = keys(load(COMPONENT / "strings.json")["entity"])
    named = {path.removesuffix(".name") for path in entities if path.endswith(".name")}
    icons = keys(load(COMPONENT / "icons.json")["entity"])
    with_icon = {
        path.removesuffix(".default") for path in icons if path.endswith(".default")
    }

    # The device tracker is deliberately absent from both: it has no
    # translation key, so it falls back to the `device_tracker` component.
    assert named == with_icon
