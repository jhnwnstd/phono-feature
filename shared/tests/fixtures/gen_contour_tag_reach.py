"""Capture the MULTISET consonant membership over all PHOIBLE
inventories: every segment that renders in MORE THAN ONE manner class
(a genuine multi-membership consonant — ``mb`` in Nasals AND Plosives, a
nasal click in Clicks AND Nasals) and the exact set of classes it lands
in. group_segments is the source of truth (it drives the coarse
assignment off ``reached_classes`` and pins each multi segment to its
existential reach, stable across inventories); this snapshot pins that
output so a regression in the gate, the reach, or the pin fails loudly.

Writes shared/tests/fixtures/contour_tag_reach.json:
  {"schema": ..., "totals": {...}, "segments": {glyph: [classes...]}}

Regenerate after an intentional grouping/gate change:
  python shared/tests/fixtures/gen_contour_tag_reach.py
(requires the baked _phoible_*.generated.json, i.e. run bake_phoible first).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# shared/tests/fixtures/ -> repo root is parents[3]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "shared" / "src"))

from phonology_shared.editor.phoible_provider import (  # noqa: E402
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine  # noqa: E402


def build_reach_map(
    provider: PhoibleProvider, inventories: list[dict]
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Materialize every inventory and collect, per glyph, the set of
    manner classes it renders in whenever that set has MORE THAN ONE
    member (a multi-membership consonant). A glyph's multiset membership
    is stable across inventories (the pin makes it a function of the
    tiers), so first occurrence wins. Returns ``(seg_membership,
    totals)``; shared by the fixture generator and the faithfulness test
    so both compute identically."""
    seg_membership: dict[str, list[str]] = {}
    multi_occurrences = 0
    inventories_with_multi = 0
    for entry in inventories:
        inv = materialize_phoible_inventory(provider, entry["id"])
        groups = FeatureEngine(inv).grouped_segments
        membership: dict[str, set[str]] = defaultdict(set)
        for name, segs in groups.items():
            for seg in segs:
                membership[seg].add(name)
        multi = {s: m for s, m in membership.items() if len(m) > 1}
        if multi:
            inventories_with_multi += 1
        for seg, classes in multi.items():
            multi_occurrences += 1
            if seg not in seg_membership:
                seg_membership[seg] = sorted(classes)
    totals = {
        "multi_occurrences": multi_occurrences,
        "unique_glyphs": len(seg_membership),
        "inventories_with_multi": inventories_with_multi,
    }
    return dict(sorted(seg_membership.items())), totals


def main() -> int:
    editor = REPO / "shared" / "src" / "phonology_shared" / "editor"
    idx = json.loads((editor / "_phoible_index.generated.json").read_text())
    dat = json.loads((editor / "_phoible_data.generated.json").read_text())
    prov = PhoibleProvider(index_table=idx, data_table=dat)

    seg_membership, totals = build_reach_map(prov, idx["inventories"])

    out = {
        "schema": "contour-multiset-membership/2",
        "note": (
            "Multiset consonant membership over PHOIBLE: each glyph that "
            "renders in more than one manner class, and the classes it "
            "lands in. group_segments is the source of truth (coarse "
            "assignment off reached_classes, then each multi segment is "
            "pinned to its existential reach so membership is stable). "
            "Regenerate with shared/tests/fixtures/gen_contour_tag_reach.py."
        ),
        "totals": totals,
        "segments": seg_membership,
    }
    dest = REPO / "shared" / "tests" / "fixtures" / "contour_tag_reach.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"multi-membership occurrences: {totals['multi_occurrences']}")
    print(f"unique glyphs: {totals['unique_glyphs']}")
    print(f"inventories with a multi segment: {totals['inventories_with_multi']}")
    hist = Counter(len(v) for v in seg_membership.values())
    print("classes-per-glyph histogram:", dict(sorted(hist.items())))
    for g in list(seg_membership)[:15]:
        print(f"  {g!r:12} -> {seg_membership[g]}")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
