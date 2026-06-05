"""Pin :py:func:`group_segments` output for every bundled inventory.

This is the regression net for the consonants grouper. The snapshot
is a BASELINE, not a freeze: deliberate improvements to the grouper
(a new typed-fact breakout, a better place derivation, an
alias-aware feature read) are expected to drift the snapshot, and
the right response is to regenerate it and review the diff for
whether the new grouping is better. The test fails so unintended
REGRESSIONS surface -- a refactor that splits Plosives in half by
accident, a code-path that drops Sibilants entirely -- not so that
every change is blocked.

Snapshot file: :file:`shared/tests/data/consonants_grouping_snapshot.json`.
Format: ``{inventory_filename: {group_label: [segment, ...]}}``.

Regenerate after an intentional change with::

    python3 - <<'PY'
    import json
    from pathlib import Path
    from phonology_shared.chart.consonants import group_segments
    from phonology_shared.data.inventory import Inventory
    snapshot = {}
    for p in sorted(Path('desktop/inventories').glob('*.json')):
        if p.name.startswith(('_', '.')): continue
        inv = Inventory.parse(
            json.loads(p.read_text(encoding='utf-8-sig')),
            source=str(p),
        )
        snapshot[p.name] = {
            g: list(s) for g, s in group_segments(inv.segments).items()
        }
    Path('shared/tests/data/consonants_grouping_snapshot.json').write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True)
    )
    PY

then ``git diff shared/tests/data/consonants_grouping_snapshot.json``
to review the new baseline before committing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart.consonants import group_segments
from phonology_shared.data.inventory import Inventory

INVENTORIES = Path(__file__).resolve().parents[2] / "desktop" / "inventories"
SNAPSHOT_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "consonants_grouping_snapshot.json"
)


def _load_snapshot() -> dict[str, dict[str, list[str]]]:
    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"missing snapshot at {SNAPSHOT_PATH}; regenerate via the "
            f"helper in the module docstring"
        )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _load_inventory(inventory_name: str) -> Inventory:
    path = INVENTORIES / inventory_name
    if not path.exists():
        pytest.skip(f"missing inventory: {inventory_name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return Inventory.parse(raw, source=str(path))


def test_grouping_matches_snapshot_for_every_bundled_inventory() -> None:
    """Walk every bundled inventory, run :py:func:`group_segments`,
    diff against the JSON snapshot. Any drift surfaces here; review
    the per-inventory diff in the failure message and either
    (a) fix the regression, or (b) regenerate the snapshot if the
    new behaviour is better.
    """
    snapshot = _load_snapshot()
    drifts: list[str] = []
    for inv_name in sorted(snapshot):
        inv = _load_inventory(inv_name)
        actual = {g: list(s) for g, s in group_segments(inv.segments).items()}
        expected = snapshot[inv_name]
        if actual != expected:
            extra_groups = set(actual) - set(expected)
            missing_groups = set(expected) - set(actual)
            common_drift: list[str] = []
            for g in sorted(set(actual) & set(expected)):
                if actual[g] != expected[g]:
                    common_drift.append(
                        f"    {g!r}: order/membership drift\n"
                        f"      expected: {expected[g]}\n"
                        f"      actual:   {actual[g]}"
                    )
            parts = [f"{inv_name}:"]
            if extra_groups:
                parts.append(f"  unexpected groups: {sorted(extra_groups)}")
            if missing_groups:
                parts.append(f"  missing groups:    {sorted(missing_groups)}")
            parts.extend(common_drift)
            drifts.append("\n".join(parts))
    assert not drifts, "group_segments drift from snapshot:\n\n" + "\n\n".join(
        drifts
    )


def test_snapshot_covers_every_bundled_inventory() -> None:
    """The snapshot must include every non-underscore-prefixed
    inventory in ``desktop/inventories/``. Adding a new bundled
    inventory is the trigger for regenerating the snapshot; this
    test surfaces the omission so the regeneration cannot be
    silently forgotten.
    """
    snapshot = _load_snapshot()
    bundled: set[str] = set()
    for path in INVENTORIES.glob("*.json"):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        bundled.add(path.name)
    missing_from_snapshot = bundled - set(snapshot)
    assert not missing_from_snapshot, (
        f"bundled inventories not in snapshot: "
        f"{sorted(missing_from_snapshot)}; regenerate via the helper "
        f"in the module docstring"
    )
