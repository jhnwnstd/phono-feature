"""Phonological segment and feature engine.

Holds one validated ``Inventory`` and answers analytical queries on it:
feature lookups, natural classes, contrast checks, segment distances.
GUI-free.

The engine takes the inventory in its constructor. There is no
"empty engine" state to defend against, and there is no in-place
``load`` -- replacing the inventory means constructing a new engine.
The contract gain: ``self._inventory`` and its derived caches are
written exactly once, so the "caches stale relative to inventory"
class of bug is structurally impossible.

Cache strategy: cheap caches (the ``+/-/0`` segment-sets, used by
the analysis pane on every selection) build eagerly in ``__init__``.
Expensive caches that not every consumer pays for (the value-tuple
table feeding ``segment_distance``) build lazily via
``functools.cached_property``.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cached_property
from types import MappingProxyType
from typing import Any

from phonology_features._logging import get_logger
from phonology_features.engine.inventory import (
    VALID_VALUES,
    Inventory,
)

_log = get_logger(__name__)

# Singleton read-only empty mapping shared across cache entries for
# the universal-class and no-spec-found return paths. Module-level so
# every empty result is the same object -- callers cannot mutate it,
# and we don't pay an allocation per call.
_EMPTY_BUNDLE: Mapping[str, str] = MappingProxyType({})


class FeatureEngine:
    """Holds one inventory and supports analytical queries on it.

    Construct with ``FeatureEngine(inventory)`` -- or, for the common
    "load from disk" path, ``FeatureEngine.from_path(filepath)``.
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
        # GeometryAnalyzer, and is_contrastive -- the common path.
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
        # Bundle search memoization: is_natural_class and
        # compute_natural_class both delegate to find_all_minimal_bundles,
        # so calling both on the same input would re-run an
        # exponential-worst-case search. Keyed by frozenset(segments).
        # Stored as tuples of MappingProxyType so a caller cannot
        # mutate the cached result and corrupt subsequent queries on
        # the same input.
        self._bundle_cache: dict[
            frozenset[str], tuple[Mapping[str, str], ...]
        ] = {}

    @classmethod
    def from_path(cls, path: str) -> FeatureEngine:
        """Parse a JSON inventory file and return a loaded engine.
        Convenience wrapper around ``Inventory.load`` + ``__init__``."""
        return cls(Inventory.load(path))

    # ----- properties exposing the inventory as read-only views -----
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

    # ----- validation helpers -----
    def _validate_segment(self, segment: str) -> None:
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not found in inventory")

    def _validate_feature(self, feature: str) -> None:
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not found in inventory")

    @staticmethod
    def _feat_match(seg_val: str, spec_val: str) -> bool:
        """True if a segment value matches a spec value, with '0' as a wildcard."""
        return seg_val == spec_val or seg_val == "0"

    def _find_segments_unsorted(
        self,
        feature_spec: Mapping[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Match segments against a feature spec; unsorted result.

        When ``underspec_compatible`` is True, a segment's '0' counts as
        compatible with any spec value (used for natural-class analysis).
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
        """Single pass over (segment, feature) populating the three
        membership sets. Run once, in ``__init__``."""
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
        """``seg -> (val_for_feat0, val_for_feat1, ...)``. Only
        consumed by ``segment_distance``, ``find_nearest_segments``,
        and ``get_inventory_stats``. Lazy because the analysis pane
        and geometry analyzer never touch it."""
        features = self._inventory.features
        return {
            seg: tuple(feats.get(f, "0") for f in features)
            for seg, feats in self._inventory.segments.items()
        }

    @cached_property
    def contrastive_features(self) -> tuple[str, ...]:
        """Features that take both '+' and '-' in this inventory.
        Used by ``GeometryAnalyzer`` and ``get_inventory_stats``."""
        return tuple(
            f
            for f in self._inventory.features
            if self.plus_segs[f] and self.minus_segs[f]
        )

    @cached_property
    def grouped_segments(self) -> dict[str, list[str]]:
        """Display-grouped segments (Plosives, Fricatives, ...).

        Lives on the engine so the cache is tied to engine identity --
        callers don't have to remember to invalidate when swapping
        inventories; they swap engines instead.
        """
        from phonology_features.engine.segment_grouper import group_segments

        return group_segments(self._inventory.segments)

    @cached_property
    def normalized_segment_feats(self) -> dict[str, dict[str, str]]:
        """Per-segment feature bundles with names normalized to the
        segment_grouper's canonical keys. Same lifetime / invalidation
        story as ``grouped_segments``."""
        from phonology_features.engine.segment_grouper import _normalize_feats

        return {
            seg: _normalize_feats(self._inventory.segments[seg])
            for seg in self._inventory.segments
        }

    # ----- public query API -----
    def get_segment_features(self, segment: str) -> dict[str, str]:
        """Full feature bundle for ``segment``; missing features default to '0'."""
        self._validate_segment(segment)
        return {f: self.segments[segment].get(f, "0") for f in self.features}

    def get_feature_value(self, segment: str, feature: str) -> str:
        """Value of ``feature`` on ``segment`` ('+', '-', or '0')."""
        self._validate_segment(segment)
        self._validate_feature(feature)
        return self.segments[segment].get(feature, "0")

    def find_segments(
        self,
        feature_spec: Mapping[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Sorted list of segments matching a (possibly partial) feature spec.

        With ``underspec_compatible``, a segment's '0' is treated as
        compatible with any spec value.

        Note on matching semantics. The default (``False``) is STRICT:
        '0' is its own value and does not match '+' or '-'. The GUI's
        feat-to-seg query mode uses this default, so a query like
        ``{Syllabic: '-', Strident: '+'}`` returns only segments that
        are EXPLICITLY ``-syllabic`` AND EXPLICITLY ``+strident``.
        Underspec-compatible is used internally by
        ``find_all_minimal_bundles`` and the per-segment matching it
        derives from; see that method for the rationale and the
        documented gotcha.
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

        A bundle B characterises S when
        ``find_segments(B, underspec_compatible=True) == S``. Returns
        ALL bundles of the smallest size, not just one greedy solution.
        Returns ``(EMPTY_BUNDLE,)`` for the universal class, ``()``
        if S is not a natural class.

        GOTCHA. "I queried this bundle and it returned my exact
        selection, why isn't it listed as a minimal spec?"

        Reason: the minimal-spec search uses UNDERSPEC-COMPATIBLE
        matching (a segment's '0' counts as compatible with any spec
        value), while the GUI feat-to-seg query mode uses STRICT
        matching ('0' does not match '+'/'-'). Concrete example,
        English inventory:

            Selection: /t͡ʃ d͡ʒ s z ʃ ʒ/
            Engine minimal spec returned: {+CORONAL, +Strident}
            User tries: {-Syllabic, +Strident}

        Under strict matching the user's bundle returns exactly the 6
        stridents (other consonants like /b/ are ``0Strident``, so
        strict equality excludes them). Under underspec-compatible
        matching the same bundle ALSO matches /b p k m h j w/ etc.
        (their ``0Strident`` matches ``+Strident`` via the wildcard
        rule), so it describes 16 segments (not 6), and is therefore
        not a characterization of the 6.

        Why the engine chose underspec semantics: a minimal spec under
        wildcard semantics is robust against the inventory's
        underspecified slots being filled in later. If /b/ ever got
        annotated ``+Strident``, ``-Syllabic +Strident`` would
        suddenly include it; ``+CORONAL +Strident`` still wouldn't,
        because /b/ is EXPLICITLY ``-CORONAL``. The minimal spec is
        the bundle that's safe under any extension of the inventory's
        currently-unspecified values.

        If the user's expectation is "the smallest bundle that
        matches MY selected segments under strict equality," that is
        a different question from "the smallest bundle that proves
        these segments form a natural class." This engine answers the
        latter; the strict-query view is available separately via the
        GUI's feat-to-seg mode.

        Return shape is ``tuple[Mapping[str, str], ...]`` -- a tuple
        of read-only views. The same object is returned across
        cache hits, so handing back a mutable list would let a caller
        ``append`` / ``clear`` / mutate-in-place and silently corrupt
        every subsequent query on the same input.

        Implementation: hitting-set backtracking. For each segment
        outside S, find the candidate features that can exclude it,
        then search for the smallest set of candidates that hits every
        outside segment.

        Complexity: worst case ``O(C^k)`` where ``C`` is the number of
        candidate features and ``k`` the best-size bound. Branch-and-
        bound pruning typically keeps it well below the worst case.
        ``max_bundles`` is a hard ceiling on result size; if hit, the
        search terminates early -- the caller gets up to that many
        bundles rather than a hang. ``10_000`` is large enough that
        no realistic inventory hits it.

        Results are memoized per-engine on ``frozenset(segments)``.
        ``is_natural_class`` and ``compute_natural_class`` both call
        through here on the same input; the cache turns a back-to-back
        pair into one search instead of two. Memoization is safe
        because the engine and its underlying Inventory are immutable
        for their lifetime.
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

        # ------------------------------------------------------------------
        # Hitting-set search via bitmask. Number each candidate feature
        # 0..N-1; the chosen set, the "still available" set, and each
        # excluder become single Python ints. Set intersection becomes
        # ``&``, non-empty test becomes truthiness on the int. This is
        # ~7-10x faster than the previous ``set`` version (profile:
        # backtrack accounted for 95% of analysis-pane render time and
        # was dominated by Python-level set operations).
        # Python ints are arbitrary precision, so N has no hard limit;
        # the bit-count cost grows linearly with N.
        # ------------------------------------------------------------------
        # Order candidates by how often they appear in excluders --
        # heavy hitters first, so branch-and-bound prunes earlier.
        # Count is built during the same pass that collects excluders;
        # the bit numbering happens after sorting.
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
        # all_remaining[idx] = bitmask of candidates with index >= idx
        # (precomputed so the "is it still solvable from here?" check
        # is a constant-time AND instead of a set rebuild).
        all_remaining = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            all_remaining[i] = all_remaining[i + 1] | (1 << i)

        results: list[dict[str, str]] = []
        best_size: int | None = None

        def backtrack(idx: int, depth: int, chosen_bits: int) -> bool:
            """``depth`` mirrors ``bin(chosen_bits).count('1')`` but
            tracked separately to skip a popcount per call. Returns
            False once ``max_bundles`` is reached so the caller can
            terminate the recursion early."""
            nonlocal best_size
            # All excluders hit?
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
            # Pruning: can the remaining bits still hit every excluder?
            remaining_bits = all_remaining[idx]
            for eb in excluder_bits:
                if not (eb & (chosen_bits | remaining_bits)):
                    return True
            # Try including candidate[idx]
            bit = 1 << idx
            if not backtrack(idx + 1, depth + 1, chosen_bits | bit):
                return False
            # Try excluding it -- but only if the still-remaining
            # candidates (idx+1..) can still satisfy every excluder.
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

    def compute_natural_class(self, segments: list[str]) -> Mapping[str, str]:
        """One minimal feature bundle characterising the segment set.

        Returns an empty mapping for both the universal class AND for
        sets that are not natural classes. Use ``is_natural_class`` to
        disambiguate. Returned mapping is read-only (a view into the
        per-engine bundle cache).
        """
        bundles = self.find_all_minimal_bundles(segments)
        return bundles[0] if bundles else _EMPTY_BUNDLE

    def get_contrastive_features(self) -> list[str]:
        """List of features that are contrastive in the loaded inventory.
        Returns a list for back-compat; prefer the ``contrastive_features``
        tuple cached property in new code."""
        return list(self.contrastive_features)

    def common_features(self, segments: list[str]) -> dict[str, str]:
        """Features whose '+' or '-' value is shared by every given segment."""
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

    def is_natural_class(
        self, segments: list[str]
    ) -> tuple[bool, tuple[Mapping[str, str], ...]]:
        """Return ``(is_natural_class, minimal_bundles)``; bundles is
        ``()`` when False. The bundle tuple is a read-only view into
        the per-engine cache; callers may iterate but must not mutate.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return (True, bundles) if bundles else (False, ())

    def segment_distance(self, seg1: str, seg2: str) -> int:
        """Number of features whose values differ between two segments.

        '0' counts as different from '+' or '-'.
        """
        self._validate_segment(seg1)
        self._validate_segment(seg2)
        t1 = self._seg_value_tuples[seg1]
        t2 = self._seg_value_tuples[seg2]
        # ``strict=True``: t1 and t2 come from the same engine, so they
        # MUST have the same length (one entry per declared feature);
        # a mismatch is a contract bug worth surfacing.
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
        """Summary stats: name, segment/feature counts, contrastive count, avg distance.

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

