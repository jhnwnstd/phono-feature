"""Canonical list of bundled inventory stems.

Lives in its own importable module (not conftest.py) so tests that
need the list at collection time, specifically
:py:func:`pytest.mark.parametrize` decorators, can ``from
tests._inventory_names import BUNDLED_INVENTORY_NAMES``. Pytest's
conftest.py is not a regular Python module (the fixture system
loads it directly), so importing constants from it across files
fails. Promote the list here so the single-source-of-truth
guarantee stays intact across the suite.

DISCOVERED, not hand-listed. A curated tuple here drifted behind
``desktop/inventories/`` once already: six inventories landed and the
two parametrised suites reading this list never saw them, while the
docstring claimed adding one propagated everywhere. Globbing the
directory is what actually makes that claim true, and it matches how
``test_vowel_chart_golden_wire.py`` finds the same corpus.
"""

from __future__ import annotations

from pathlib import Path

_INVENTORY_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)

#: Suffix every full bundled inventory file carries. The filter also
#: excludes ``_schema.json`` (the validation contract, not an
#: inventory) and ``maximalist_vowels.json`` (a vowel-space fixture
#: with no consonants, so consonant-side assertions have nothing to
#: say about it); ``test_vowel_chart_golden_wire.py`` draws the same
#: line for the same reason.
_INVENTORY_SUFFIX = "_features.json"

#: Bundled inventory stems every test wanting per-inventory
#: parametrisation should iterate over. Dropping a new inventory into
#: ``desktop/inventories/`` propagates the case to each of them; the
#: stem is the filename with ``_features.json`` removed, which is the
#: key the ``bundled_inventory`` / ``bundled_engine`` fixtures take.
BUNDLED_INVENTORY_NAMES: tuple[str, ...] = tuple(
    sorted(
        p.name[: -len(_INVENTORY_SUFFIX)]
        for p in _INVENTORY_DIR.glob(f"*{_INVENTORY_SUFFIX}")
    )
)
