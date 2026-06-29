"""The shared dialect-trim both inventory-picker clients consume.

``display_dialect`` strips a leading copy of the search-box language
from a dialect label so a row under "Korean" reads "Seoul", not
"Korean (Seoul)". The desktop picker row and the web source card both
call it through the relay, so this pins the one algorithm they share
and guards against the two clients drifting apart again.
"""

from __future__ import annotations

import pytest

from phonology_shared.editor.inventory_providers import display_dialect


@pytest.mark.parametrize(
    "dialect, language, expected",
    [
        # Clean leading match: language + parenthesised dialect.
        ("Korean (Seoul)", "Korean", "Seoul"),
        # Clean leading match without parentheses.
        ("Korean Seoul", "Korean", "Seoul"),
        # No leading match: left unchanged.
        ("Standard Korean", "Korean", "Standard Korean"),
        # Match leaves nothing behind: keep the original label.
        ("Korean", "Korean", "Korean"),
        # Case-insensitive match, mismatch left alone.
        ("German (Bavarian)", "korean", "German (Bavarian)"),
        # Missing language: pass the dialect through.
        ("Seoul", "", "Seoul"),
        # Missing or blank dialect: empty string.
        (None, "Korean", ""),
        ("   ", "Korean", ""),
    ],
)
def test_display_dialect(
    dialect: str | None, language: str, expected: str
) -> None:
    assert display_dialect(dialect, language) == expected
