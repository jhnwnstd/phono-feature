"""Canonical list of bundled inventory stems.

Lives in its own importable module (not conftest.py) so tests that
need the list at collection time -- specifically
:py:func:`pytest.mark.parametrize` decorators -- can ``from
tests._inventory_names import BUNDLED_INVENTORY_NAMES``. Pytest's
conftest.py is not a regular Python module (the fixture system
loads it directly), so importing constants from it across files
fails. Promote the list here so the single-source-of-truth
guarantee stays intact across the suite.
"""

from __future__ import annotations

#: Bundled inventory file stems any test wanting per-inventory
#: parametrisation should iterate over. Adding a new bundled
#: inventory here propagates the case to every parametrised test.
BUNDLED_INVENTORY_NAMES: tuple[str, ...] = (
    "english",
    "hindi",
    "german",
    "japanese",
    "korean",
    "spanish",
    "lomongo",
    "mandarin_chinese",
    "modern_standard_arabic",
    "turkish",
)
