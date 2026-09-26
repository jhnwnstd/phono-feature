"""Guard the discovered bundled-inventory roster.

:py:data:`_inventory_names.BUNDLED_INVENTORY_NAMES` is globbed off
``desktop/inventories/`` and feeds ``pytest.mark.parametrize`` in
several suites. A parametrize over an EMPTY sequence collects zero
cases and passes, so a broken glob (a rename, a layout change, a
tightened suffix) would quietly retire whole suites while CI stayed
green. That is the same silent-coverage-loss shape that once hid the
grouper's affricate tests, so the roster gets its own tripwire.

The second test pins the coupling the glob depends on: the stem it
produces must be the key ``bundled_inventory`` accepts. Those two
build the filename from opposite ends (the glob strips
``_features.json``, the fixture appends it), and nothing else would
notice if they stopped meeting in the middle.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _inventory_names import BUNDLED_INVENTORY_NAMES

from phonology_shared.data.inventory import Inventory

#: The bundled set has been at or above this size since the corpus
#: grew past the original hand-listed ten. A floor rather than an
#: equality so adding an inventory needs no edit here, while a glob
#: that collapses to nothing (or nearly nothing) fails.
_MIN_EXPECTED = 10


def test_roster_is_populated() -> None:
    """Vacuous-pass tripwire for every suite parametrised on the
    roster."""
    assert len(BUNDLED_INVENTORY_NAMES) >= _MIN_EXPECTED, (
        f"discovered only {len(BUNDLED_INVENTORY_NAMES)} bundled "
        f"inventories {BUNDLED_INVENTORY_NAMES}; expected at least "
        f"{_MIN_EXPECTED}. Every suite parametrised on this roster is "
        "now running fewer cases than it claims."
    )


def test_roster_entries_are_stems_not_filenames() -> None:
    """The glob must hand back loader keys, not paths: no suffix left
    on, and neither of the two deliberate exclusions present."""
    for name in BUNDLED_INVENTORY_NAMES:
        assert not name.endswith("_features"), name
        assert not name.endswith(".json"), name
        assert name not in {"_schema", "maximalist_vowels"}, name


@pytest.mark.parametrize("name", BUNDLED_INVENTORY_NAMES)
def test_every_roster_entry_loads(
    name: str, bundled_inventory: Callable[[str], Inventory]
) -> None:
    """Each discovered stem resolves through the fixture and parses.
    Pins the glob-strips / fixture-appends contract described above."""
    inv = bundled_inventory(name)
    assert inv.segments, f"{name} parsed to an empty inventory"
    assert inv.features, f"{name} declares no features"
