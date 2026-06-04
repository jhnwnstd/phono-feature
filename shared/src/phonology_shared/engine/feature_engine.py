"""Phonological segment and feature engine.

Holds one validated :py:class:`Inventory` and answers analytical
queries on it: feature lookups, natural classes, contrast checks,
segment distances. GUI-free.

The engine takes the inventory in its constructor. There is no empty
state to defend against, and there is no in-place ``load``. Replacing
the inventory means constructing a new engine. The contract gain:
``self._inventory`` and its derived caches are written exactly once,
so the "cache stale relative to inventory" class of bug is
structurally impossible.

Cache strategy: cheap caches (the +/-/0 segment-sets used by the
analysis pane on every selection) build eagerly in ``__init__``.
Expensive caches that not every consumer pays for (the value-tuple
table feeding :py:meth:`segment_distance`) build lazily via
:py:func:`functools.cached_property`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from types import MappingProxyType
from typing import Any, Literal

from phonology_shared.engine.inventory import (
    VALID_VALUES,
    Inventory,
)
from phonology_shared.engine.segment_grouper import (
    _normalize_feats,
    group_segments,
)

_log = logging.getLogger(__name__)

# Singleton read-only empty mapping shared across the universal-class
# and no-spec-found return paths. Module-level so every empty result
# is the same object; callers cannot mutate it, and there is no
# per-call allocation.
_EMPTY_BUNDLE: Mapping[str, str] = MappingProxyType({})


class FeatureCategory(StrEnum):
    """Semantic classification of one feature against a selected set.

    The seven categories capture every possible mix of ``+``/``-``/``'0'``
    values across the selection. They are the single source of truth
    for what "shared" and "contrastive" mean and which features can
    contribute to a natural-class specification:

    * ``ALL_PLUS`` / ``ALL_MINUS``: every selected segment has the
      same explicit value. The feature contributes to a STRICT
      minimal specification.
    * ``ALL_ZERO``: every selected segment is ``'0'``. The feature
      carries no information about the selection; it cannot
      contribute to any spec.
    * ``EXPLICIT_CONFLICT``: some selected segments are ``'+'`` and
      others are ``'-'``; none is ``'0'``. The feature explicitly
      splits the selection; cannot contribute to a shared spec.
    * ``UNDERSPEC_PLUS`` / ``UNDERSPEC_MINUS``: some selected
      segments have the explicit value, the rest are ``'0'``. The
      feature could contribute to a strictly-underspec-tolerant
      spec but NOT to a strict spec (which requires every member
      to have the explicit value). The user-facing analysis pane
      reports this as "shared under underspecification".
    * ``UNDERSPEC_CONFLICT``: ``+``, ``-``, and ``'0'`` all appear.
      The conflict cannot be erased by underspecification: any
      strict-and-underspec spec including this feature would
      contradict at least one selected segment. The feature is
      contrastive AND involves underspecification; UI may render
      it distinctly from ``EXPLICIT_CONFLICT``.

    Strict natural-class detection (the contract the round-trip
    invariant rests on) only considers ``ALL_PLUS`` and ``ALL_MINUS``
    features as bundle candidates -- this is what ensures any spec
    the engine LISTS round-trips exactly through
    :py:meth:`find_segments`.
    """

    ALL_PLUS = "all_plus"
    ALL_MINUS = "all_minus"
    ALL_ZERO = "all_zero"
    EXPLICIT_CONFLICT = "explicit_conflict"
    UNDERSPEC_PLUS = "underspec_plus"
    UNDERSPEC_MINUS = "underspec_minus"
    UNDERSPEC_CONFLICT = "underspec_conflict"


CompletionStatus = Literal[
    "already_natural_class",
    "one_minimal_completion",
    "multiple_minimal_completions",
]


@dataclass(frozen=True, slots=True)
class NaturalClassCompletion:
    """Result of :py:meth:`FeatureEngine.complete_to_minimal_natural_class`.

    Two concepts are kept on a hard API boundary so the UI cannot
    mistakenly display one as if it were the other:

    * **Concept A — definition of the selected set.** Applies when
      ``S`` is already a strict natural class. Carried in
      :py:attr:`selected_minimal_bundles`: the minimal feature
      bundle(s) ``B`` such that ``find_segments(B) == S``.
    * **Concept B — completion of the selected set.** Applies when
      ``S`` is NOT a strict natural class. Carried in
      :py:attr:`additions`: the smallest addition set(s) ``A`` such
      that ``S ∪ A`` is a strict natural class.

    The dataclass deliberately does NOT carry the minimal bundles
    of the completed class ``S ∪ A``. Computing them is an
    exponential-worst-case hitting-set search and is unused on the
    not-a-natural-class verdict path. Callers that genuinely need
    those bundles can recover them with
    :py:meth:`FeatureEngine.find_all_minimal_bundles` on
    ``selected + list(additions[i])``.

    :py:attr:`status` discriminates the three outcomes:

    * ``"already_natural_class"``: only
      :py:attr:`selected_minimal_bundles` is populated;
      :py:attr:`additions` is empty.
    * ``"one_minimal_completion"``: :py:attr:`additions` has one
      element (the unique minimum addition set);
      :py:attr:`selected_minimal_bundles` is empty.
    * ``"multiple_minimal_completions"``: reserved. Under strict-
      bundle semantics the minimum addition set is provably
      unique (see the algorithm docstring), so the present solver
      never emits this status. The value is kept on the Literal
      and the outer-tuple shape on :py:attr:`additions` is kept
      general so a future, more permissive solver could populate
      multiple distinct minimum addition sets without a breaking
      change.

    The universal class (whole inventory, empty bundle) is always
    a valid containing natural class, so :py:attr:`additions` is
    non-empty whenever the verdict is "No" — the solver never
    fails to find a completion.
    """

    status: CompletionStatus
    selected_minimal_bundles: tuple[Mapping[str, str], ...]
    additions: tuple[tuple[str, ...], ...]


class FeatureEngine:
    """Holds one inventory and answers analytical queries on it.

    Construct with ``FeatureEngine(inventory)`` or, for the common
    load-from-disk path, ``FeatureEngine.from_path(filepath)``.

    **Immutability contract.** Both :py:class:`FeatureEngine` and
    its backing :py:class:`Inventory` are immutable after
    construction. Every expensive derivation
    (``contrastive_features``, ``grouped_segments``,
    ``normalized_segment_feats``, the per-segment value tuples) is
    a :py:func:`functools.cached_property` whose invalidation
    boundary is the constructor itself: there is no "edit the
    inventory in place" path, so caches can never go stale. To
    replace the inventory, construct a new engine; do not add an
    in-place edit method without also writing the matching cache-
    clear logic.

    The bridge in ``web/api.py`` rebinds the module-level
    ``_engine`` to a fresh ``FeatureEngine`` on every
    ``load_inventory_json`` call and invalidates its own LRU
    caches via ``_invalidate_analysis_caches``; the desktop
    constructs a new engine per inventory load too.
    """

    def __init__(self, inventory: Inventory) -> None:
        if not isinstance(inventory, Inventory):
            raise TypeError(
                f"FeatureEngine requires an Inventory, "
                f"got {type(inventory).__name__}. "
                f"Use Inventory.parse(raw_dict) or Inventory.load(path) first."
            )
        self._inventory = inventory
        # Per-feature segment-set caches built once at construction.
        # Used by analysis.compute_contrastive (every selection change),
        # GeometryAnalyzer, and is_contrastive.
        self.spec_segs: dict[str, frozenset[str]] = {}
        self.plus_segs: dict[str, frozenset[str]] = {}
        self.minus_segs: dict[str, frozenset[str]] = {}
        self._build_membership_caches()
        _log.debug(
            "engine constructed: %r (%d segments, %d features)",
            inventory.name,
            len(inventory.segments),
            len(inventory.features),
        )
        # Bundle-search memoization. is_natural_class and
        # compute_natural_class both delegate to
        # find_all_minimal_bundles, so calling both on the same input
        # would re-run an exponential-worst-case search. Keyed by
        # frozenset(segments). Stored as tuples of MappingProxyType so
        # a caller cannot mutate the cached result and corrupt
        # subsequent queries on the same input.
        self._bundle_cache: dict[
            frozenset[str], tuple[Mapping[str, str], ...]
        ] = {}

    @classmethod
    def from_path(cls, path: str) -> FeatureEngine:
        """Parse a JSON inventory file and return a loaded engine."""
        return cls(Inventory.load(path))

    @property
    def inventory(self) -> Inventory:
        """The currently-loaded validated Inventory."""
        return self._inventory

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._inventory.metadata

    @property
    def features(self) -> tuple[str, ...]:
        return self._inventory.features

    @property
    def segments(self) -> Mapping[str, Mapping[str, str]]:
        return self._inventory.segments

    def _validate_segment(self, segment: str) -> None:
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not found in inventory")

    def _validate_feature(self, feature: str) -> None:
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not found in inventory")

    @staticmethod
    def _feat_match(seg_val: str, spec_val: str) -> bool:
        """Underspec-compatible value match: equal values, or the
        segment's value is ``'0'`` (underspecified, treated as
        wildcard against the spec). The spec's ``'0'`` is NOT
        wild; only the segment side relaxes. Reached only via
        :py:meth:`_find_segments_unsorted` with
        ``underspec_compatible=True``; the strict default path
        compares with plain ``==``.
        """
        return seg_val == spec_val or seg_val == "0"

    def _is_natural_class_bool(self, segments: list[str]) -> bool:
        """Fast boolean: does ``segments`` form a natural class?

        Strict semantics: a set ``S`` is a natural class iff there
        exists a feature bundle ``B`` such that
        ``find_segments(B) == S`` under the default strict equality
        (``'0' != '+' != '-'``). This is the same predicate the user
        gets when typing into the feat→seg pane, so the analysis
        pane's "natural class" verdict and the typed-query round-
        trip cannot disagree.

        Skips the minimal-bundle enumeration that
        :py:meth:`find_all_minimal_bundles` performs and answers the
        decision question directly using the precomputed membership
        sets. Complexity is ``O(F + O*C)`` where F = features,
        O = outside segments, C = candidate (feature, value) pairs
        -- never exponential, no backtracking.

        Theory: under strict matching, a feature is a candidate for
        the bundle iff every selected segment has the **same
        explicit** value on it (``'0'`` segments disqualify the
        feature). The set is a natural class iff those candidate
        features collectively exclude every outside segment, where
        "(f, +) excludes t" means t is not explicitly ``+`` on f
        (including the case t is ``'0'``). If they do, taking ALL
        candidates yields a valid characterising bundle; if they
        don't, no subset does either.
        """
        if not segments:
            # ``∅`` is not a strict natural class: no bundle ``B``
            # satisfies ``find_segments(B) == ∅``. Matches the
            # contract pinned by :py:meth:`find_all_minimal_bundles`.
            return False
        selected: frozenset[str] = frozenset(segments)
        cached = self._bundle_cache.get(selected)
        if cached is not None:
            return len(cached) > 0
        all_segments = self._all_segments
        if not selected <= all_segments:
            bad = next(iter(selected - all_segments))
            raise KeyError(f"Segment '{bad}' not in inventory")
        outside = all_segments - selected
        if not outside:
            return True
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        candidates = self._strict_candidate_constraints(selected)
        # Outside coverage under strict matching: (f, +) excludes
        # outside t iff t is NOT explicitly + on f. That's the
        # complement of plus_segs[f] within outside, which includes
        # both explicit '-' and '0' segments.
        covered: set[str] = set()
        for feat, val in candidates.items():
            if val == "+":
                covered |= outside - plus_segs[feat]
            else:
                covered |= outside - minus_segs[feat]
            if covered == outside:
                return True
        return covered == outside

    def _find_segments_unsorted(
        self,
        feature_spec: Mapping[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Match segments against a feature spec; unsorted result.

        Default is strict equality (the same matching rule the
        user-typed feat->seg query uses). Computed via membership-
        set intersections so it stays vertical-set-shaped like the
        rest of the engine -- a fresh ``find_segments(B)`` call is
        an ``O(F)`` walk over the spec, intersecting the relevant
        ``plus_segs[f]``, ``minus_segs[f]``, or
        ``all_segments - spec_segs[f]`` (for ``'0'``) into the
        running match set.

        With ``underspec_compatible=True``, the segment's ``'0'``
        is treated as wildcard via :py:meth:`_feat_match`. No
        engine method currently uses the underspec path; it is
        kept on the public API for callers that want to gather a
        candidate pool of segments not in explicit disagreement
        with a query. That path still scans because the wildcard
        rule isn't expressible as a single membership intersection.
        """
        if underspec_compatible:
            match = self._feat_match
            matching = []
            for segment, features in self.segments.items():
                if all(
                    match(features.get(f, "0"), v)
                    for f, v in feature_spec.items()
                ):
                    matching.append(segment)
            return matching
        # Strict path: build the match set by membership intersection.
        matched: frozenset[str] = self._all_segments
        for feature, value in feature_spec.items():
            if value == "+":
                matched &= self.plus_segs[feature]
            elif value == "-":
                matched &= self.minus_segs[feature]
            else:
                # ``'0'`` is its own value: segments NOT in spec_segs.
                matched -= self.spec_segs[feature]
            if not matched:
                break
        return list(matched)

    def _build_membership_caches(self) -> None:
        """Populate the three membership sets in one pass."""
        features = self._inventory.features
        segments = self._inventory.segments
        spec: dict[str, set[str]] = {f: set() for f in features}
        plus: dict[str, set[str]] = {f: set() for f in features}
        minus: dict[str, set[str]] = {f: set() for f in features}
        for seg, feats in segments.items():
            for f in features:
                v = feats.get(f, "0")
                if v == "+":
                    spec[f].add(seg)
                    plus[f].add(seg)
                elif v == "-":
                    spec[f].add(seg)
                    minus[f].add(seg)
        self.spec_segs = {f: frozenset(s) for f, s in spec.items()}
        self.plus_segs = {f: frozenset(s) for f, s in plus.items()}
        self.minus_segs = {f: frozenset(s) for f, s in minus.items()}
        # Universe of segment names. Held as a frozenset because the
        # natural-class fast path repeatedly computes
        # ``all_segments - selected_subset``; on each call that would
        # otherwise rebuild a fresh set from the segments mapping.
        # Frozen because the inventory (and therefore this universe)
        # never changes after construction.
        self._all_segments: frozenset[str] = frozenset(
            self._inventory.segments
        )

    @cached_property
    def _seg_value_tuples(self) -> dict[str, tuple[str, ...]]:
        """``seg -> (val_for_feat0, val_for_feat1, ...)``.

        Only consumed by :py:meth:`segment_distance`,
        :py:meth:`find_nearest_segments`, and
        :py:meth:`get_inventory_stats`. Lazy because the analysis pane
        and geometry analyzer never touch it.
        """
        features = self._inventory.features
        return {
            seg: tuple(feats.get(f, "0") for f in features)
            for seg, feats in self._inventory.segments.items()
        }

    @cached_property
    def contrastive_features(self) -> tuple[str, ...]:
        """Features that take both '+' and '-' in this inventory."""
        return tuple(
            f
            for f in self._inventory.features
            if self.plus_segs[f] and self.minus_segs[f]
        )

    @cached_property
    def grouped_segments(self) -> dict[str, list[str]]:
        """Display-grouped segments (Plosives, Fricatives, ...).

        Lives on the engine so the cache is tied to engine identity.
        Callers do not have to remember to invalidate when swapping
        inventories; they swap engines instead.
        """
        return group_segments(self._inventory.segments)

    @cached_property
    def normalized_segment_feats(self) -> dict[str, dict[str, str]]:
        """Per-segment feature bundles with names normalized to the
        :py:mod:`segment_grouper` canonical keys. Same lifetime and
        invalidation story as :py:attr:`grouped_segments`."""
        return {
            seg: _normalize_feats(self._inventory.segments[seg])
            for seg in self._inventory.segments
        }

    def get_segment_features(self, segment: str) -> dict[str, str]:
        """Full feature bundle for ``segment``. Missing features
        default to ``'0'``."""
        self._validate_segment(segment)
        return {f: self.segments[segment].get(f, "0") for f in self.features}

    def get_feature_value(self, segment: str, feature: str) -> str:
        """Value of ``feature`` on ``segment`` (``'+'``, ``'-'``, or
        ``'0'``)."""
        self._validate_segment(segment)
        self._validate_feature(feature)
        return self.segments[segment].get(feature, "0")

    def find_segments(
        self,
        feature_spec: Mapping[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Sorted list of segments matching a (possibly partial) spec.

        With ``underspec_compatible``, a segment's ``'0'`` is treated
        as compatible with any spec value.

        Matching semantics. The default (``False``) is STRICT:
        ``'0'`` is its own value and does not match ``'+'`` or
        ``'-'``. The GUI's feat-to-seg query mode uses this default,
        so a query ``{Syllabic: '-', Strident: '+'}`` returns only
        segments that are explicitly ``-syllabic`` AND explicitly
        ``+strident``. ``underspec_compatible=True`` is a public
        relaxation path with no current internal consumer; the
        natural-class engine itself (:py:meth:`find_all_minimal_bundles`,
        :py:meth:`_is_natural_class_bool`) does not call this
        method and runs entirely on the precomputed +/- membership
        sets.
        """
        for feature, value in feature_spec.items():
            self._validate_feature(feature)
            if value not in VALID_VALUES:
                raise ValueError(
                    f"Invalid feature value '{value}' for '{feature}'"
                )
        return sorted(
            self._find_segments_unsorted(
                feature_spec, underspec_compatible=underspec_compatible
            )
        )

    def find_all_minimal_bundles(
        self,
        segments: list[str],
        *,
        max_bundles: int = 10_000,
    ) -> tuple[Mapping[str, str], ...]:
        """Every minimal feature bundle that characterises the segment set.

        **Strict semantics:** a bundle ``B`` characterises ``S`` iff
        ``find_segments(B) == S`` under the default strict equality
        (``'0' != '+' != '-'``). The round-trip invariant: any
        bundle this method returns, when typed into the feat→seg
        pane, returns exactly ``S``. Candidate features are
        restricted to those where EVERY selected segment has the
        same explicit value (``'0'`` disqualifies the feature);
        outside-segment exclusion treats ``'0'`` as a distinct
        value that does NOT match ``'+'`` or ``'-'``.

        Returns ``(EMPTY_BUNDLE,)`` ONLY for the universal class
        (the whole inventory selected). Returns ``()`` for any
        non-NC set, including the empty selection (``find_segments({})``
        is the whole inventory under strict matching, so the empty
        bundle does NOT characterise ``∅``). The empty-tuple case
        is the common one for non-NC sets where some member is
        ``'0'`` on a feature that would otherwise be discriminating;
        the user-facing UI presents these as "not a natural class"
        and surfaces a suggested completion via
        :py:meth:`complete_to_minimal_natural_class`.

        Returns up to ``max_bundles`` minimal bundles; the search
        terminates early once that many are found. The current
        return type does not distinguish "all minimal bundles" from
        "the first N" -- consumers that need to know whether the
        result was truncated should compare ``len(result)`` to
        ``max_bundles`` and re-query with a higher limit if needed.

        Return shape is ``tuple[Mapping[str, str], ...]``: a tuple
        of read-only views. The same object is returned across
        cache hits, so handing back a mutable list would let a
        caller append/clear/mutate-in-place and silently corrupt
        every subsequent query on the same input.

        Implementation: hitting-set backtracking with bitmask
        representation. For each segment outside ``S``, find the
        candidate features that can exclude it, then search for
        the smallest set of candidates that hits every outside
        segment.

        Complexity: worst case ``O(C^k)`` where ``C`` is the
        number of candidate features and ``k`` the best-size
        bound. Branch-and-bound pruning typically keeps it well
        below the worst case.

        Results are memoized per-engine on ``frozenset(segments)``.
        Safe because the engine and its underlying Inventory are
        immutable for their lifetime.
        """
        if not segments:
            # ``∅`` is not a strict natural class: there is no bundle
            # ``B`` with ``find_segments(B) == ∅`` (the empty bundle's
            # extent is the whole inventory). Callers special-case
            # the empty selection at the UI layer.
            return ()
        seg_map = self._inventory.segments
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        all_segments = self._all_segments
        for seg in segments:
            if seg not in seg_map:
                raise KeyError(f"Segment '{seg}' not in inventory")
        cache_key: frozenset[str] = frozenset(segments)
        cached = self._bundle_cache.get(cache_key)
        if cached is not None:
            return cached
        # Strict candidate collection: a feature is a candidate only
        # when EVERY selected segment has the same explicit value.
        # ``'0'`` cells in the selection disqualify the feature,
        # which is exactly what gives the round-trip invariant: any
        # bundle returned here, typed into the feat pane, returns
        # the input set under strict equality.
        candidates = self._strict_candidate_constraints(cache_key)
        outside_set = all_segments - cache_key
        if not outside_set:
            self._bundle_cache[cache_key] = (_EMPTY_BUNDLE,)
            return self._bundle_cache[cache_key]
        # Preserve the historical iteration order of ``outside`` so
        # ``raw_excluders`` lines up with ``outside`` indices the same
        # way the old code did. Iterating ``seg_map`` (an insertion-
        # ordered dict) gives a stable order matching the inventory
        # declaration.
        outside = [s for s in seg_map if s in outside_set]

        # Hitting-set search via bitmask. Each candidate feature gets
        # a bit index 0..N-1; the chosen set, the still-available set,
        # and each excluder become single Python ints. Set
        # intersection is ``&``, non-empty test is truthiness. This is
        # ~7-10x faster than the previous set-based version; the
        # previous profile had backtrack at 95% of analysis-pane
        # render time, dominated by Python-level set operations.
        # Python ints are arbitrary precision, so N has no hard limit;
        # the bit-count cost grows linearly with N.
        #
        # Candidates are ordered by how often they appear in
        # excluders, heavy hitters first, so branch-and-bound prunes
        # earlier. Counts are built during the same pass that collects
        # excluders; the bit numbering happens after sorting.
        feat_to_bit: dict[str, int] = {}
        excluder_bits: list[int] = []
        counts: dict[str, int] = dict.fromkeys(candidates, 0)
        raw_excluders: list[list[str]] = []
        # Strict excluder collection: outside t is excluded by
        # (f, +) iff t is not explicitly ``+`` on f -- so
        # ``outside - plus_segs[f]`` covers explicit ``-`` and
        # ``'0'`` segments alike. Strict matching treats ``'0'`` as
        # a distinct value, which is what the user-typed feat→seg
        # query uses; bundles emitted here round-trip exactly.
        excludes_by: dict[str, frozenset[str]] = {}
        for feat, val in candidates.items():
            target = plus_segs[feat] if val == "+" else minus_segs[feat]
            excludes_by[feat] = outside_set - target
        for seg in outside:
            exc_feats = [
                feat
                for feat, excluded in excludes_by.items()
                if seg in excluded
            ]
            if not exc_feats:
                self._bundle_cache[cache_key] = ()
                return self._bundle_cache[cache_key]
            raw_excluders.append(exc_feats)
            for f in exc_feats:
                counts[f] += 1
        candidate_list = sorted(
            candidates.keys(), key=lambda f: counts[f], reverse=True
        )
        for i, f in enumerate(candidate_list):
            feat_to_bit[f] = 1 << i
        for exc_feats in raw_excluders:
            mask = 0
            for f in exc_feats:
                mask |= feat_to_bit[f]
            excluder_bits.append(mask)
        n = len(candidate_list)
        # all_remaining[idx] is the bitmask of candidates with index
        # >= idx, precomputed so the "still solvable from here?" check
        # is a constant-time AND instead of a set rebuild.
        all_remaining = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            all_remaining[i] = all_remaining[i + 1] | (1 << i)

        results: list[dict[str, str]] = []
        best_size: int | None = None

        def backtrack(idx: int, depth: int, chosen_bits: int) -> bool:
            """``depth`` mirrors ``bin(chosen_bits).count('1')`` but
            is tracked separately to skip a popcount per call. Returns
            False once ``max_bundles`` is reached so the caller can
            terminate the recursion early."""
            nonlocal best_size
            satisfied = True
            for eb in excluder_bits:
                if not (eb & chosen_bits):
                    satisfied = False
                    break
            if satisfied:
                if best_size is None or depth < best_size:
                    best_size = depth
                    results.clear()
                    results.append(_bits_to_bundle(chosen_bits))
                elif depth == best_size:
                    results.append(_bits_to_bundle(chosen_bits))
                return len(results) < max_bundles
            if best_size is not None and depth >= best_size:
                return True
            if idx >= n:
                return True
            # Can the remaining bits still hit every excluder?
            remaining_bits = all_remaining[idx]
            for eb in excluder_bits:
                if not (eb & (chosen_bits | remaining_bits)):
                    return True
            bit = 1 << idx
            if not backtrack(idx + 1, depth + 1, chosen_bits | bit):
                return False
            # Try excluding the candidate, but only if the
            # still-remaining candidates (idx+1..) can still satisfy
            # every excluder without it.
            remaining_without = all_remaining[idx + 1]
            for eb in excluder_bits:
                if not (eb & (chosen_bits | remaining_without)):
                    return True
            return backtrack(idx + 1, depth, chosen_bits)

        def _bits_to_bundle(bits: int) -> dict[str, str]:
            return {
                candidate_list[i]: candidates[candidate_list[i]]
                for i in range(n)
                if bits & (1 << i)
            }

        backtrack(0, 0, 0)
        frozen = tuple(MappingProxyType(b) for b in results)
        self._bundle_cache[cache_key] = frozen
        return frozen

    def compute_natural_class(
        self, segments: list[str]
    ) -> Mapping[str, str] | None:
        """One minimal feature bundle characterising the segment set.

        Three distinct return shapes:

        * a non-empty mapping: the minimal feature bundle.
        * an empty mapping: the segments form the universal class
          (every segment in the inventory).
        * ``None``: the segments are not a natural class.

        The mapping (when not ``None``) is read-only, a view into
        the per-engine bundle cache.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return bundles[0] if bundles else None

    def get_contrastive_features(self) -> list[str]:
        """List of features that are contrastive in the loaded
        inventory. Returns a list for back-compat; prefer the
        :py:attr:`contrastive_features` tuple in new code.
        """
        return list(self.contrastive_features)

    def feature_categories(
        self, segments: list[str]
    ) -> dict[str, FeatureCategory]:
        """Classify every feature against the selected segment set
        into one of seven categories (see
        :py:class:`FeatureCategory`).

        Single source of truth for what "shared", "contrastive",
        and "underspecified" mean. View-models read this once per
        analysis and surface the category in the per-feature row
        state so renderers can show distinct visuals (e.g.
        ``UNDERSPEC_CONFLICT`` rendered differently from
        ``EXPLICIT_CONFLICT``) without inventing their own
        classification logic.

        Empty selection returns an empty dict (no selection => no
        categorisation).
        """
        if not segments:
            return {}
        selected: frozenset[str] = frozenset(segments)
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        spec_segs = self.spec_segs
        n = len(selected)
        out: dict[str, FeatureCategory] = {}
        for feat in self._inventory.features:
            plus_hit = len(selected & plus_segs[feat])
            minus_hit = len(selected & minus_segs[feat])
            spec_hit = len(selected & spec_segs[feat])
            all_specified = spec_hit == n
            if all_specified:
                if plus_hit == n:
                    out[feat] = FeatureCategory.ALL_PLUS
                elif minus_hit == n:
                    out[feat] = FeatureCategory.ALL_MINUS
                else:
                    out[feat] = FeatureCategory.EXPLICIT_CONFLICT
                continue
            if plus_hit == 0 and minus_hit == 0:
                out[feat] = FeatureCategory.ALL_ZERO
            elif plus_hit > 0 and minus_hit == 0:
                out[feat] = FeatureCategory.UNDERSPEC_PLUS
            elif minus_hit > 0 and plus_hit == 0:
                out[feat] = FeatureCategory.UNDERSPEC_MINUS
            else:
                out[feat] = FeatureCategory.UNDERSPEC_CONFLICT
        return out

    def common_features(self, segments: list[str]) -> dict[str, str]:
        """Features whose ``'+'`` or ``'-'`` value is shared by every
        given segment.

        Identical to the strict natural-class candidate rule -- a
        feature is "shared" iff every selected segment has the same
        explicit value on it. Delegates to
        :py:meth:`_strict_candidate_constraints` so the strict-NC
        contract has one source of truth across this method,
        :py:meth:`_is_natural_class_bool`,
        :py:meth:`find_all_minimal_bundles`, and
        :py:meth:`complete_to_minimal_natural_class`.
        """
        if not segments:
            return {}
        for seg in segments:
            self._validate_segment(seg)
        return self._strict_candidate_constraints(frozenset(segments))

    def _strict_candidate_constraints(
        self, selected: frozenset[str]
    ) -> dict[str, str]:
        """Strict candidate constraints of ``selected``.

        Returns ``{feature: value}`` for every feature where
        ``selected ⊆ plus_segs[f]`` (value ``'+'``) or
        ``selected ⊆ minus_segs[f]`` (value ``'-'``). These are the
        only (feature, value) pairs a strict natural-class bundle
        can use without disqualifying some member of ``selected``,
        and are also exactly the features whose value is shared by
        every member.

        Does not validate ``selected``; callers that need an
        ``ValueError`` on unknown segments must do that check first
        (this is the engine-internal hot path).
        """
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        candidates: dict[str, str] = {}
        for feature in self._inventory.features:
            if selected <= plus_segs[feature]:
                candidates[feature] = "+"
            elif selected <= minus_segs[feature]:
                candidates[feature] = "-"
        return candidates

    def project_segments_to_features(
        self, segments: list[str]
    ) -> dict[str, str]:
        """Translate a segment selection into an equivalent
        feature-query spec, suitable for prefilling a feat-to-seg
        panel after switching modes from seg-to-feat.

        Returns the common +/- features of the selection (drops
        ``'0'`` values; the user can re-add underspecification
        deliberately). Empty input produces an empty spec.

        Single source of truth for the seg-to-feat side of the GUI's
        mode-switch projection: the desktop's
        ``ModeController.save_outgoing_state`` and the web bridge
        both call this, so both frontends produce identical
        pre-filled states on toggle.

        The reverse direction (feat-to-seg projection) is just
        :py:meth:`find_segments`.
        """
        return {
            f: v
            for f, v in self.common_features(segments).items()
            if v in ("+", "-")
        }

    def complete_to_minimal_natural_class(
        self, segments: list[str]
    ) -> NaturalClassCompletion:
        """The smallest strict natural class containing ``segments``.

        Returns a :py:class:`NaturalClassCompletion`. The two
        concepts are kept on a hard API boundary by field name:

        * ``already_natural_class`` → ``selected_minimal_bundles``
          carries the minimal feature bundles of ``S`` (Concept A:
          definition of the selected set). ``additions`` is empty.
        * ``one_minimal_completion`` → ``additions = ((seg, seg, ...),)``
          carries the segments needed to complete ``S`` into a
          strict natural class (Concept B).
          ``selected_minimal_bundles`` is empty because ``S`` is not
          itself a natural class. If the caller needs the minimal
          specs of the COMPLETED class (Concept A applied to
          ``S ∪ additions[0]``), it can call
          :py:meth:`find_all_minimal_bundles` separately --
          intentionally NOT computed here because the not-a-natural-
          class UI path does not display them and the hitting-set
          search is exponential worst case.

        The third status ``multiple_minimal_completions`` is part of
        the contract for general correctness but is unreachable from
        the present solver: under strict-bundle semantics the
        minimum addition set is provably unique.

        **Algorithm.** Intersect the constraint-sets of every
        strict-shared candidate constraint:

            ``smallest_class = ∩ {plus_segs[f] | S ⊆ plus_segs[f]}``
            ``                  ∩ {minus_segs[f] | S ⊆ minus_segs[f]}``

        ``additions = smallest_class - S``.

        **Guaranteed exact.** No search budget, no fallback. The
        universal class (empty bundle, whole inventory) is itself
        a strict natural class containing any selection, so when
        no candidate constraints exist the function returns the
        universal completion exactly rather than degrading.

        **Cost.** One ``find_all_minimal_bundles`` call on ``S``
        (the already-NC fast path; cached) plus an ``O(F)``
        intersection over features. No exponential work on the
        not-a-natural-class path.
        """
        if not segments:
            return NaturalClassCompletion(
                status="already_natural_class",
                selected_minimal_bundles=(),
                additions=(),
            )
        seg_map = self._inventory.segments
        for seg in segments:
            if seg not in seg_map:
                raise KeyError(f"Segment '{seg}' not in inventory")
        own_bundles = self.find_all_minimal_bundles(segments)
        if own_bundles:
            return NaturalClassCompletion(
                status="already_natural_class",
                selected_minimal_bundles=own_bundles,
                additions=(),
            )
        # ``S`` is not a strict NC. Build the smallest strict NC
        # containing it by intersecting every selection-safe
        # constraint set. An empty constraint set leaves
        # ``smallest_class`` at ``_all_segments`` (the universal
        # class), which is itself always a valid containing NC.
        selected = frozenset(segments)
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        smallest_class: frozenset[str] = self._all_segments
        for feat, val in self._strict_candidate_constraints(selected).items():
            if val == "+":
                smallest_class &= plus_segs[feat]
            else:
                smallest_class &= minus_segs[feat]
        # Inventory-declaration order so the UI gets a stable,
        # human-meaningful sequence of additions.
        additions_set = smallest_class - selected
        additions_tuple = tuple(s for s in seg_map if s in additions_set)
        return NaturalClassCompletion(
            status="one_minimal_completion",
            selected_minimal_bundles=(),
            additions=(additions_tuple,),
        )

    def is_natural_class(
        self, segments: list[str]
    ) -> tuple[bool, tuple[Mapping[str, str], ...]]:
        """Return ``(is_natural_class, minimal_bundles)``.

        Strict semantics: a set is a natural class iff some feature
        bundle ``B`` satisfies ``find_segments(B) == segments``
        under the default strict equality (``'0' != '+' != '-'``,
        what the user gets when typing into the feat pane). This
        gives the round-trip invariant: any bundle this method
        returns, when typed into feat→seg, returns exactly the
        input set.

        Returns ``(False, ())`` when no strict bundle exists. The
        UI presents these as "not a natural class" and offers the
        :py:meth:`complete_to_minimal_natural_class` completion --
        the smallest set of segments to add so the union does form
        a strict natural class.

        The bundle tuple is a read-only view into the per-engine
        cache; callers may iterate but must not mutate.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return bool(bundles), bundles

    def segment_distance(self, seg1: str, seg2: str) -> int:
        """Number of features whose values differ between two
        segments. ``'0'`` counts as different from ``'+'`` or
        ``'-'``."""
        self._validate_segment(seg1)
        self._validate_segment(seg2)
        t1 = self._seg_value_tuples[seg1]
        t2 = self._seg_value_tuples[seg2]
        # ``strict=True``: t1 and t2 come from the same engine, so
        # they must have the same length. A mismatch is a contract
        # bug worth surfacing.
        return sum(1 for a, b in zip(t1, t2, strict=True) if a != b)

    def find_nearest_segments(
        self, segment: str, n: int = 5
    ) -> list[tuple[str, int]]:
        """``n`` closest segments to ``segment`` by feature distance."""
        self._validate_segment(segment)
        distances = [
            (other, self.segment_distance(segment, other))
            for other in self.segments
            if other != segment
        ]
        distances.sort(key=lambda x: (x[1], x[0]))
        return distances[:n]

    def get_inventory_stats(self) -> dict[str, int | float | str]:
        """Summary stats: name, segment/feature counts, contrastive
        count, average distance.

        ``avg_feature_distance`` is ``O(n^2 * |features|)`` over the
        inventory and is recomputed on every call. Callers that hit
        this on a hot path should cache the result themselves.
        """
        name = self.metadata.get("name", "Unknown")
        stats: dict[str, int | float | str] = {
            "name": str(name),
            "segment_count": len(self.segments),
            "feature_count": len(self.features),
            "contrastive_features": len(self.get_contrastive_features()),
        }
        if len(self.segments) > 1:
            tuples = list(self._seg_value_tuples.values())
            n = len(tuples)
            total = 0
            for i in range(n):
                ti = tuples[i]
                for j in range(i + 1, n):
                    tj = tuples[j]
                    total += sum(
                        1 for a, b in zip(ti, tj, strict=True) if a != b
                    )
            count = n * (n - 1) // 2
            stats["avg_feature_distance"] = total / count
        else:
            stats["avg_feature_distance"] = 0.0
        return stats
