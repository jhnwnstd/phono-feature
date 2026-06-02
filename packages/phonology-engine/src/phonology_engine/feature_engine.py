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
from functools import cached_property
from types import MappingProxyType
from typing import Any

from phonology_engine.inventory import (
    VALID_VALUES,
    Inventory,
)
from phonology_engine.segment_grouper import (
    _normalize_feats,
    group_segments,
)

_log = logging.getLogger(__name__)

# Singleton read-only empty mapping shared across the universal-class
# and no-spec-found return paths. Module-level so every empty result
# is the same object; callers cannot mutate it, and there is no
# per-call allocation.
_EMPTY_BUNDLE: Mapping[str, str] = MappingProxyType({})


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
        """True if a segment value matches a spec value, with '0'
        treated as a wildcard."""
        return seg_val == spec_val or seg_val == "0"

    def _find_segments_unsorted(
        self,
        feature_spec: Mapping[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Match segments against a feature spec; unsorted result.

        With ``underspec_compatible``, a segment's '0' counts as
        compatible with any spec value (used for natural-class
        analysis).
        """
        match = self._feat_match if underspec_compatible else None
        matching = []
        for segment, features in self.segments.items():
            if match is not None:
                ok = all(
                    match(features.get(f, "0"), v)
                    for f, v in feature_spec.items()
                )
            else:
                ok = all(
                    features.get(f, "0") == v for f, v in feature_spec.items()
                )
            if ok:
                matching.append(segment)
        return matching

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

        Matching semantics. The default (``False``) is STRICT: ``'0'``
        is its own value and does not match ``'+'`` or ``'-'``. The
        GUI's feat-to-seg query mode uses this default, so a query
        ``{Syllabic: '-', Strident: '+'}`` returns only segments that
        are explicitly ``-syllabic`` AND explicitly ``+strident``.
        Underspec-compatible is used internally by
        :py:meth:`find_all_minimal_bundles` and the per-segment
        matching it derives; see that method for the rationale and
        the documented gotcha.
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

        A bundle ``B`` characterises ``S`` when
        ``find_segments(B, underspec_compatible=True) == S``. Returns
        ALL bundles of the smallest size, not just one greedy
        solution. Returns ``(EMPTY_BUNDLE,)`` for the universal class,
        and ``()`` if ``S`` is not a natural class.

        Gotcha: "I queried this bundle and it returned my exact
        selection, why is it not listed as a minimal spec?"

        Reason: the minimal-spec search uses UNDERSPEC-COMPATIBLE
        matching (a segment's ``'0'`` counts as compatible with any
        spec value), while the GUI feat-to-seg query mode uses STRICT
        matching (``'0'`` does not match ``'+'``/``'-'``). Concrete
        example using the English inventory:

            Selection: /t͡ʃ d͡ʒ s z ʃ ʒ/
            Engine minimal spec returned: {+CORONAL, +Strident}
            User tries: {-Syllabic, +Strident}

        Under strict matching the user's bundle returns exactly the 6
        stridents (other consonants like /b/ are ``0Strident``, so
        strict equality excludes them). Under underspec-compatible
        matching the same bundle ALSO matches /b p k m h j w/ and
        their relatives (their ``0Strident`` matches ``+Strident`` via
        the wildcard rule), so it describes 16 segments, not 6, and
        is therefore not a characterization of the 6.

        Why underspec semantics: a minimal spec under wildcard
        matching is robust against the inventory's underspecified
        slots being filled in later. If /b/ were ever annotated
        ``+Strident``, ``{-Syllabic, +Strident}`` would suddenly
        include it; ``{+CORONAL, +Strident}`` still would not because
        /b/ is explicitly ``-CORONAL``. The minimal spec is the
        bundle that is safe under any extension of the inventory's
        currently-unspecified values.

        If the user's question is "the smallest bundle that matches
        MY selected segments under strict equality", that is a
        different question from "the smallest bundle that proves
        these segments form a natural class". This engine answers
        the latter; the strict-query view is available via the GUI's
        feat-to-seg mode.

        Return shape is ``tuple[Mapping[str, str], ...]``: a tuple of
        read-only views. The same object is returned across cache
        hits, so handing back a mutable list would let a caller
        append/clear/mutate-in-place and silently corrupt every
        subsequent query on the same input.

        Implementation: hitting-set backtracking with bitmask
        representation. For each segment outside ``S``, find the
        candidate features that can exclude it, then search for the
        smallest set of candidates that hits every outside segment.

        Complexity: worst case ``O(C^k)`` where ``C`` is the number
        of candidate features and ``k`` the best-size bound.
        Branch-and-bound pruning typically keeps it well below the
        worst case. ``max_bundles`` is a hard ceiling on result size;
        if hit, the search terminates early.

        Results are memoized per-engine on ``frozenset(segments)``.
        is_natural_class and compute_natural_class both call through
        here on the same input; the cache turns a back-to-back pair
        into one search instead of two. Safe because the engine and
        its underlying Inventory are immutable for their lifetime.
        """
        if not segments:
            return (_EMPTY_BUNDLE,)
        for seg in segments:
            if seg not in self.segments:
                raise ValueError(f"Segment '{seg}' not in inventory")
        cache_key = frozenset(segments)
        cached = self._bundle_cache.get(cache_key)
        if cached is not None:
            return cached
        segment_set = set(segments)
        candidates: dict[str, str] = {}
        for feature in self.features:
            values = {self.segments[seg].get(feature, "0") for seg in segments}
            specified = values - {"0"}
            if len(specified) == 1:
                candidates[feature] = specified.pop()
        outside = [s for s in self.segments if s not in segment_set]
        if not outside:
            self._bundle_cache[cache_key] = (_EMPTY_BUNDLE,)
            return self._bundle_cache[cache_key]

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
        for seg in outside:
            exc_feats = [
                feat
                for feat, val in candidates.items()
                if not self._feat_match(self.segments[seg].get(feat, "0"), val)
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

    def common_features(self, segments: list[str]) -> dict[str, str]:
        """Features whose ``'+'`` or ``'-'`` value is shared by every
        given segment."""
        if not segments:
            return {}
        for seg in segments:
            self._validate_segment(seg)
        result = {}
        for feature in self.features:
            values = {self.segments[seg].get(feature, "0") for seg in segments}
            if len(values) == 1:
                v = values.pop()
                if v != "0":
                    result[feature] = v
        return result

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

    def suggest_natural_class_extension(
        self, segments: list[str]
    ) -> list[str]:
        """The smallest set of segments that, added to ``segments``,
        completes it into a natural class.

        Returns ``[]`` when ``segments`` is already a natural class
        or has no shared +/- features to extend by. Single source of
        truth for the "N segments needed for natural class" UX hint
        used by both the desktop and the web bridge.

        Algorithm: candidates are the segments that share the
        ``common_features`` of the selection (under-spec compatible)
        but aren't selected. The MAXIMAL completion ``S ∪ candidates``
        is always a natural class (characterised by ``common``), so a
        completion exists. We search by ascending subset size and
        return the first subset where ``is_natural_class(S ∪ subset)``
        holds. This is the MINIMAL completion size.

        Why this matters: ``common_features`` uses strict-shared
        matching (all selected segments must have the same explicit
        value), so it misses features where one of the selected
        segments has ``'0'`` (underspecified). ``is_natural_class``
        uses ``find_all_minimal_bundles`` which understands underspec
        as a wildcard, so it can find tighter bundles that match the
        selection plus a SUBSET of the candidates. The maximal
        completion overestimates how many more segments are needed.

        Example (Blevins): selecting /b͡v/ /d͡z/ /t͡s/ shares only
        ``{-ConstrGl, +DelRel, -Lateral}``, giving 7 candidate
        affricates. But adding just /p͡f/ alone makes the union a
        natural class via the bundle
        ``{-DORSAL, -Sonorant, +DelRel, +Strident, +Anterior,
        -Distributed, -Lateral}`` — underspec wildcards on /b͡v/
        and /p͡f/ for Anterior let this tighter spec match. The
        minimal completion is ``[p͡f]``, not all 7 candidates.

        Search budget: caps at ``MAX_SEARCH_CALLS`` so a pathological
        candidate pool (rare in real inventories) doesn't hang the
        UI; falls back to the full extension in that case.
        """
        from itertools import combinations

        is_nc, _ = self.is_natural_class(segments)
        if is_nc:
            return []
        common = self.common_features(segments)
        if not common:
            return []
        selected = set(segments)
        candidates = [
            s
            for s in self.find_segments(common, underspec_compatible=True)
            if s not in selected
        ]
        if not candidates:
            return []
        # Ascending subset size; first valid combination wins. The
        # full ``candidates`` set is always valid (characterised by
        # ``common``), so the loop always returns before the
        # fallback below.
        max_search_calls = 2000
        calls = 0
        for k in range(1, len(candidates) + 1):
            for combo in combinations(candidates, k):
                calls += 1
                if calls > max_search_calls:
                    # Pathological pool; fall back to the full
                    # extension. The "N needed" hint becomes
                    # conservative (overestimate) but never wrong.
                    return list(candidates)
                if self.is_natural_class(list(segments) + list(combo))[0]:
                    return list(combo)
        # Unreachable in practice — the full extension is always a
        # valid completion — but return it for safety.
        return list(candidates)

    def is_natural_class(
        self, segments: list[str]
    ) -> tuple[bool, tuple[Mapping[str, str], ...]]:
        """Return ``(is_natural_class, minimal_bundles)``.

        ``bundles`` is ``()`` when ``is_natural_class`` is False.
        The bundle tuple is a read-only view into the per-engine
        cache; callers may iterate but must not mutate.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return (True, bundles) if bundles else (False, ())

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
