"""Standing guard: reached_classes' SINGLE-PHASE FAST PATH stays equal to
the tiers round-trip it shortcuts.

``reached_classes`` (chart/consonants.py) has a fast path: when a segment
has no genuine contour (every value sequence is length 1, ~96% of PHOIBLE
segments) it uses the normalized bundle directly as its sole phase instead
of building singleton tiers and running ``_reach_phase_bundles`` over them.
That shortcut is correct only while, for every such segment, TWO
sub-invariants hold:

  (A) VALUE-FOLD SEAM. Each singleton sequence value equals the normalized
      bundle value: ``seg_seqs[f][0] == norm.get(f, "0")``. True because
      normalization folds the feature KEY and never the VALUE, and
      ``Inventory.sequences`` builds each singleton straight from the same
      raw cell the normalized bundle reads. A future normalization change
      that starts folding a VALUE (not just a key) breaks this silently:
      the fast path reads the folded value, the slow path the raw one.

  (B) ROUND-TRIP IDENTITY. The reconstructed slow tiers collapse to a
      single phase equal to the bundle (the ragged onset/offset branch of
      ``_reach_phase_bundles`` never fires for all-singleton input), so the
      one phase the fast path uses is exactly the one phase the slow path
      would have produced.

Neither is frozen by the multiset membership guards: those pin the
``grouped_segments`` OUTPUT and only for multi-membership (>= 2 class)
glyphs, so a value-fold that flips a SINGLE-class segment's reach never
touches that fixture and would pass silently. This guard closes that seam,
loudly, over the whole corpus.

The corpus population counts are pinned as FLOORS, not exact totals: the
PHOIBLE snapshot is refreshed by ``update_phoible.py`` and exact counts
would churn on a benign data bump, whereas the divergence tallies are
pinned exactly at zero. Today the bake yields 100,996 fast-path segment
occurrences across 2,176 distinct glyphs; the floors sit ~10% below so a
refactor that silently empties the fast-path population (routing every
segment through the slow path) still fails loudly rather than passing
vacuously.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from phonology_shared.chart.consonants import (
    _reach_phase_bundles,
    reached_classes,
)
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine

_SHARED_SRC = Path(__file__).resolve().parents[1] / "src"

# Floors from the current bake (100,996 fast-path segments / 2,176 distinct
# glyphs). FLOORS, not exact counts, so a PHOIBLE refresh does not churn the
# test; only the divergence tallies below are pinned exactly at zero.
_MIN_FAST_SEGMENTS = 90_000
_MIN_FAST_GLYPHS = 2_000


def _force_slow(
    norm: Mapping[str, str], seg_seqs: Mapping[str, Sequence[str]]
) -> set[str]:
    """``reached_classes`` for an all-singleton segment, forced down its
    SLOW branch.

    ``reached_classes`` takes the slow (tiers -> ``_reach_phase_bundles``)
    branch as soon as any value sequence is longer than one. Duplicating
    ONE sequence value into a length-2 CONSTANT tier flips it there while
    leaving the answer unchanged: every membership gate is an ``any(...)``
    over the phase list and two byte-identical phases union to the
    single-phase result, so a constant tier is answer-preserving.

    The duplicated value comes from ``seg_seqs`` (never the normalized
    bundle), so the forced slow path reads the sequence value at every
    feature. That is the point: if a value-fold ever makes
    ``seg_seqs[f][0] != norm[f]``, the fast path (which reads ``norm``) and
    this slow path (which reads ``seg_seqs``) diverge and the caller's
    equality assertion fails. Duplicating the NORM value instead would pin
    the feature back to the fast path's own value and mask exactly that.
    """
    feat = next(iter(seg_seqs))
    dup = seg_seqs[feat][0]
    forced = {**seg_seqs, feat: (dup, dup)}
    return reached_classes(norm, forced)


def test_single_phase_fast_path_round_trip_identity_unit() -> None:
    """Non-corpus guard (runs everywhere, even without the bake): for an
    all-singleton bundle the slow round-trip collapses to one phase equal
    to the bundle, and ``reached_classes`` agrees whether it takes the fast
    branch (singleton sequences) or is forced down the slow branch. Pins
    sub-invariant B and the fast/slow equivalence on a hand-built segment
    so the seam is protected in a CI run that ships without the snapshot.
    """
    for norm in (
        # a plain plosive: reaches exactly one class
        {
            "consonantal": "+",
            "sonorant": "-",
            "continuant": "-",
            "syllabic": "-",
        },
        # a stop-closure with delayed release: exercises delrel_plus, which
        # the fast and slow branches derive differently
        {
            "consonantal": "+",
            "sonorant": "-",
            "continuant": "-",
            "delrel": "+",
            "syllabic": "-",
        },
    ):
        singleton = {f: (v,) for f, v in norm.items()}
        # (B) round-trip identity: exactly one phase, dict-equal to norm,
        # so the ragged onset/offset branch never fired.
        assert _reach_phase_bundles(singleton) == [dict(norm)]
        # The singleton sequences do not perturb the fast path, and forcing
        # the slow branch yields the identical class set.
        assert reached_classes(norm, {}) == reached_classes(norm, singleton)
        assert reached_classes(norm, singleton) == _force_slow(norm, singleton)
        # guard against a vacuous set()==set(): the bundle reaches a class.
        assert reached_classes(norm, singleton)


def _provider() -> tuple[PhoibleProvider, list[dict[str, object]]]:
    editor = _SHARED_SRC / "phonology_shared" / "editor"
    idx_path = editor / "_phoible_index.generated.json"
    dat_path = editor / "_phoible_data.generated.json"
    if not (idx_path.exists() and dat_path.exists()):
        pytest.skip("baked PHOIBLE snapshot absent; run bake_phoible first")
    idx = json.loads(idx_path.read_text())
    dat = json.loads(dat_path.read_text())
    return PhoibleProvider(index_table=idx, data_table=dat), idx["inventories"]


def test_single_phase_fast_path_matches_tiers_round_trip_over_corpus() -> None:
    """Over the whole PHOIBLE corpus, every fast-path (all-singleton)
    segment's reach equals what the tiers round-trip would produce, and
    every singleton sequence value equals the normalized value (the
    value-fold seam). Fails loudly the moment a normalization change folds
    a value rather than only a key, or the round-trip stops collapsing to
    one phase. Population floors keep it from passing vacuously if the
    fast-path population is ever silently emptied."""
    provider, inventories = _provider()
    segments = 0
    glyphs: set[str] = set()
    value_fold_divergences: list[tuple[str, str, str, str, str]] = []
    reach_divergences: list[tuple[str, str, list[str], list[str]]] = []

    for entry in inventories:
        inv_id = str(entry["id"])
        eng = FeatureEngine(materialize_phoible_inventory(provider, inv_id))
        norms = eng.normalized_segment_feats
        for sym, seg_seqs in eng._sequences_by_seg.items():
            # EXACT fast-path predicate (consonants.py): a genuine contour
            # (some sequence longer than one) takes the slow path and is out
            # of scope; an empty bundle cannot be force-slowed.
            if not seg_seqs or any(len(t) > 1 for t in seg_seqs.values()):
                continue
            norm = norms[sym]
            segments += 1
            glyphs.add(sym)
            # The seam relies on seg_seqs' keys being a superset of norm's
            # (a sequence override may add a key; a singleton is never
            # dropped), so pin that assumption before quantifying over it.
            assert set(norm) <= set(seg_seqs), (inv_id, sym)
            # (A) value-fold seam, per cell. Use norm.get(f, "0") because a
            # sequence-only key reads as "0" in the fast path's bundle.
            for feat, tier in seg_seqs.items():
                if tier[0] != norm.get(feat, "0"):
                    value_fold_divergences.append(
                        (inv_id, sym, feat, tier[0], norm.get(feat, "0"))
                    )
            # End-to-end: the fast path (singleton sequences) and the forced
            # slow path (a constant length-2 tier through the REAL
            # _reach_phase_bundles) must reach the identical class set.
            fast = reached_classes(norm, seg_seqs)
            slow = _force_slow(norm, seg_seqs)
            if fast != slow:
                reach_divergences.append(
                    (inv_id, sym, sorted(fast), sorted(slow))
                )

    assert not value_fold_divergences, value_fold_divergences[:20]
    assert not reach_divergences, reach_divergences[:20]
    # Non-vacuity: the fast path must actually be exercised.
    assert segments >= _MIN_FAST_SEGMENTS, segments
    assert len(glyphs) >= _MIN_FAST_GLYPHS, len(glyphs)
