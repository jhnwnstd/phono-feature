"""Capture the CURRENT 'Contour Consonants' tagged population across all
PHOIBLE inventories, and for each tagged segment the set of manner
classes it EXISTENTIALLY reaches (some phase satisfies the class's
is_member test) plus the affricate ∃-rule. This is the ground-truth
fixture the deferred multi-membership pass validates against: those same
segments should render in exactly these classes when the partition
becomes a multiset.

Writes shared/tests/fixtures/contour_tag_reach.json:
  {"schema": ..., "class_specs": {...}, "segments": {glyph: [classes...]}}

Regenerate after an intentional change to the gate / tag rule:
  python shared/tests/fixtures/gen_contour_tag_reach.py
(requires the baked _phoible_*.generated.json, i.e. run bake_phoible first).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# shared/tests/fixtures/ -> repo root is parents[3]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "shared" / "src"))

from phonology_shared.chart.consonants import (  # noqa: E402
    _MIN_POSITIVE,
    CONTOUR_GROUP_NAME,
    PRIMARY_GROUPS,
    TONES_GROUP_NAME,
    VOWEL_GROUP_NAME,
)
from phonology_shared.data.inventory import (  # noqa: E402
    normalize_feature_key,
)
from phonology_shared.data.tiers import Aligned, Attrs, align  # noqa: E402
from phonology_shared.editor.phoible_provider import (  # noqa: E402
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine  # noqa: E402

# Consonant manner specs the ∃-reach considers (drop the hard-gated
# Clicks / Vowels / Tones; Clicks is handled by an explicit ∃click test).
_CONSONANT_SPECS = [
    (name, spec)
    for name, spec in PRIMARY_GROUPS
    if name not in ("Clicks", VOWEL_GROUP_NAME, TONES_GROUP_NAME)
]

# Pulmonic-obstruent specs a click's oral closure must NOT spuriously
# satisfy: a click is its own (velaric) airstream, so best_primary hard-
# gates it to Clicks and never Plosives/Fricatives. Nasality/sonorance
# are orthogonal (a nasal click IS nasal), so those specs still see a
# click phase.
_CLICK_EXCLUDES = frozenset({"Plosives", "Fricatives"})


def _phase_bundles(tiers: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
    """Every phase of the segment as a {feature: value} bundle. Aligned
    segments give their aligned columns; a ragged (Misaligned) segment
    gives its two total anchors (onset + offset), the endpoints the
    source pins even when the interior has no derivable alignment."""
    attrs = Attrs(sorted(tiers))
    aln = align(attrs, tiers)
    if isinstance(aln, Aligned):
        n = len(aln.phases)
        return [
            {f: (t[i] if len(t) == n else t[0]) for f, t in tiers.items()}
            for i in range(n)
        ]
    onset = {f: t[0] for f, t in tiers.items()}
    offset = {f: t[-1] for f, t in tiers.items()}
    return [onset, offset]


def _bundle_matches(
    bundle: dict[str, str], spec: dict[str, str], min_pos: int
) -> bool:
    """is_member's positive-evidence test on one phase bundle (universal
    active features): count spec features the bundle states matching, and
    require >= min_pos. Major class is guarded by the caller."""
    matched = 0
    for feat, want in spec.items():
        val = bundle.get(feat, "0")
        if val == "0":
            continue
        if val != want:
            return False
        matched += 1
    return matched >= min_pos


def _reach(tiers: dict[str, tuple[str, ...]]) -> list[str]:
    """The manner classes this segment existentially reaches, mirroring
    the engine's is_member / best_primary / affricate_group per phase.

    ``tiers`` MUST be keyed by the engine's canonical feature name
    (``normalize_feature_key``), so ``Velaric`` reads as ``click`` and a
    click routes to Clicks rather than leaking into the obstruent specs.
    """
    phases = _phase_bundles(tiers)
    reached: set[str] = set()
    if any(b.get("click") == "+" for b in phases):
        reached.add("Clicks")
    # affricate ∃-rule (mirrors affricate_group's obstruent guards per
    # phase): some phase is a non-click obstruent stop CLOSURE, and the
    # segment carries a delayed release. This rejects a nasal-onset
    # contour (ŋ->h) and a nasal click, whose only [-cont] phase is a
    # sonorant, not an affricate closure.
    has_closure = any(
        b.get("consonantal") == "+"
        and b.get("sonorant") != "+"
        and b.get("continuant") == "-"
        and b.get("click") != "+"
        for b in phases
    )
    if has_closure and "+" in tiers.get("delrel", ()):
        reached.add("Affricates")
    for name, spec in _CONSONANT_SPECS:
        min_pos = _MIN_POSITIVE.get(name, 1)
        for bundle in phases:
            # major-class guard: skip a phase that is a vowel or tone
            if (
                bundle.get("syllabic") == "+"
                and bundle.get("consonantal") != "+"
            ):
                continue
            if (
                bundle.get("tone") == "+"
                and bundle.get("consonantal") != "+"
                and bundle.get("syllabic") != "+"
            ):
                continue
            # a click's oral closure is not a pulmonic obstruent
            if bundle.get("click") == "+" and name in _CLICK_EXCLUDES:
                continue
            if _bundle_matches(bundle, spec, min_pos):
                reached.add(name)
                break
    return sorted(reached)


def build_reach_map(
    provider: PhoibleProvider, inventories: list[dict]
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Materialize every inventory, collect the 'Contour Consonants'
    tagged segments, and compute each glyph's ∃-reach ONCE (a glyph's
    reach is a function of its tiers, stable across inventories). Returns
    ``(seg_reach, totals)``. Shared by the fixture generator and the
    full-corpus faithfulness test so both compute identically."""
    seg_reach: dict[str, list[str]] = {}
    tagged_occurrences = 0
    inventories_with_tag = 0
    for entry in inventories:
        inv = materialize_phoible_inventory(provider, entry["id"])
        eng = FeatureEngine(inv)
        tagged = eng.grouped_segments.get(CONTOUR_GROUP_NAME, [])
        if tagged:
            inventories_with_tag += 1
        for seg in tagged:
            tagged_occurrences += 1
            if seg in seg_reach:
                continue
            tiers = {
                normalize_feature_key(k): tuple(v)
                for k, v in inv.sequences(seg).items()
            }
            seg_reach[seg] = _reach(tiers)
    totals = {
        "tagged_occurrences": tagged_occurrences,
        "unique_glyphs": len(seg_reach),
        "inventories_with_tag": inventories_with_tag,
    }
    return dict(sorted(seg_reach.items())), totals


def main() -> int:
    E = REPO / "shared" / "src" / "phonology_shared" / "editor"
    idx = json.loads((E / "_phoible_index.generated.json").read_text())
    dat = json.loads((E / "_phoible_data.generated.json").read_text())
    prov = PhoibleProvider(index_table=idx, data_table=dat)

    seg_reach, totals = build_reach_map(prov, idx["inventories"])

    out = {
        "schema": "contour-tag-reach/1",
        "note": (
            "The CURRENT 'Contour Consonants' tagged population and, per "
            "glyph, the manner classes it existentially reaches (some "
            "phase satisfies the class is_member test; plus the affricate "
            "∃-rule). This is the roadmap fixture for the deferred multi-"
            "membership pass: when group_segments becomes a multiset, each "
            "of these glyphs should render in exactly these classes. "
            "Regenerate with shared/tests/fixtures/gen_contour_tag_reach.py."
        ),
        "class_specs": dict(_CONSONANT_SPECS),
        "totals": totals,
        "segments": seg_reach,
    }
    dest = REPO / "shared" / "tests" / "fixtures" / "contour_tag_reach.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"tagged occurrences: {totals['tagged_occurrences']}")
    print(f"unique glyphs: {totals['unique_glyphs']}")
    print(f"inventories with tag: {totals['inventories_with_tag']}")
    from collections import Counter

    multi = Counter(len(v) for v in seg_reach.values())
    print("∃-classes-per-glyph histogram:", dict(sorted(multi.items())))
    # show a sample
    for g in list(seg_reach)[:15]:
        print(f"  {g!r:12} -> {seg_reach[g]}")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
