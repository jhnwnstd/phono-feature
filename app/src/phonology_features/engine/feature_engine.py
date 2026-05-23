"""Phonological segment and feature engine.

Holds one validated ``Inventory`` and answers analytical queries on it:
feature lookups, natural classes, contrast checks, segment distances.
GUI-free.

The engine never accepts a raw dict. Callers parse first
(``Inventory.parse``, ``Inventory.load``) so validation and engine
construction share one contract -- the engine doesn't get to be more
lenient (or stricter) than the validator. Mutations require building
a new ``Inventory`` and calling ``load`` again; this is what keeps the
per-feature caches in sync with the active inventory.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from phonology_features.engine.inventory import (
    VALID_VALUES,
    Inventory,
)


class FeatureEngine:
    """Holds one inventory and supports analytical queries on it."""

    def __init__(self) -> None:
        # Pre-load state: an empty inventory so attribute access never
        # explodes. Real inventory arrives via ``load`` / ``load_path``.
        self._inventory: Inventory = Inventory(
            name="",
            metadata=MappingProxyType({}),
            features=(),
            segments=MappingProxyType({}),
        )
        # Per-feature segment-set caches built by _rebuild_caches.
        # Read-only. Rebuilt on every ``load``; cannot desynchronize
        # because the underlying Inventory is frozen.
        self.spec_segs: dict[str, frozenset[str]] = {}
        self.plus_segs: dict[str, frozenset[str]] = {}
        self.minus_segs: dict[str, frozenset[str]] = {}
        self._seg_value_tuples: dict[str, tuple[str, ...]] = {}
        self._contrastive_features: list[str] | None = None

    # ----- inventory loading -----
    def load(self, inventory: Inventory) -> None:
        """Adopt an already-validated ``Inventory`` and rebuild caches.

        The Inventory is frozen so there is no risk of caller mutation
        desynchronizing engine caches. To change the inventory, build a
        new ``Inventory`` and call ``load`` again.
        """
        if not isinstance(inventory, Inventory):
            raise TypeError(
                f"FeatureEngine.load requires an Inventory, "
                f"got {type(inventory).__name__}. "
                f"Use Inventory.parse(raw_dict) or Inventory.load(path) first."
            )
        self._inventory = inventory
        self._rebuild_caches()

    def load_path(self, path: str) -> None:
        """Convenience: parse a JSON file into an Inventory and load it."""
        self.load(Inventory.load(path))

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
        feature_spec: dict[str, str],
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

    def _rebuild_caches(self) -> None:
        """Rebuild derived per-feature segment-sets and value tuples.

        Called by every load path. The engine exposes no public
        mutators; rebuilding only happens via ``load``.
        """
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
        self._seg_value_tuples = {
            seg: tuple(feats.get(f, "0") for f in features)
            for seg, feats in segments.items()
        }
        self._contrastive_features = None

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
        feature_spec: dict[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Sorted list of segments matching a (possibly partial) feature spec.

        With ``underspec_compatible``, a segment's '0' is treated as
        compatible with any spec value.
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
    ) -> list[dict[str, str]]:
        """Every minimal feature bundle that characterises the segment set.

        A bundle B characterises S when
        ``find_segments(B, underspec_compatible=True) == S``. Returns
        ALL bundles of the smallest size, not just one greedy solution.
        Returns ``[{}]`` for the universal class, ``[]`` if S is not a
        natural class.

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
        """
        if not segments:
            return [{}]
        for seg in segments:
            if seg not in self.segments:
                raise ValueError(f"Segment '{seg}' not in inventory")
        segment_set = set(segments)
        candidates: dict[str, str] = {}
        for feature in self.features:
            values = {self.segments[seg].get(feature, "0") for seg in segments}
            specified = values - {"0"}
            if len(specified) == 1:
                candidates[feature] = specified.pop()
        outside = [s for s in self.segments if s not in segment_set]
        if not outside:
            return [{}]
        excluders: list[set[str]] = []
        for seg in outside:
            exc: set[str] = {
                feat
                for feat, val in candidates.items()
                if not self._feat_match(self.segments[seg].get(feat, "0"), val)
            }
            if not exc:
                return []
            excluders.append(exc)
        candidate_list = sorted(
            candidates.keys(),
            key=lambda f: sum(1 for exc in excluders if f in exc),
            reverse=True,
        )
        n = len(candidate_list)
        results: list[dict[str, str]] = []
        best_size: int | None = None

        def backtrack(
            idx: int, chosen: list[str], chosen_set: set[str]
        ) -> bool:
            """Returns False once ``max_bundles`` is reached; the
            caller stops descending so the search terminates."""
            nonlocal best_size
            if all(exc & chosen_set for exc in excluders):
                k = len(chosen)
                if best_size is None or k < best_size:
                    best_size = k
                    results.clear()
                    results.append({f: candidates[f] for f in chosen})
                elif k == best_size:
                    results.append({f: candidates[f] for f in chosen})
                return len(results) < max_bundles
            if best_size is not None and len(chosen) >= best_size:
                return True
            if idx >= n:
                return True
            remaining = set(candidate_list[idx:])
            if not all(
                (exc & chosen_set) or (exc & remaining) for exc in excluders
            ):
                return True
            f = candidate_list[idx]
            if not backtrack(idx + 1, [*chosen, f], chosen_set | {f}):
                return False
            remaining_without = set(candidate_list[idx + 1 :])
            if all(
                (exc & chosen_set) or (exc & remaining_without)
                for exc in excluders
            ):
                if not backtrack(idx + 1, chosen, chosen_set):
                    return False
            return True

        backtrack(0, [], set())
        return results

    def compute_natural_class(self, segments: list[str]) -> dict[str, str]:
        """One minimal feature bundle characterising the segment set.

        Returns ``{}`` for both the universal class AND for sets that
        are not natural classes. Use ``is_natural_class`` to disambiguate.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return bundles[0] if bundles else {}

    def is_contrastive(self, feature: str) -> bool:
        """True if the feature takes both '+' and '-' across the inventory."""
        self._validate_feature(feature)
        return bool(self.plus_segs[feature]) and bool(self.minus_segs[feature])

    def get_contrastive_features(self) -> list[str]:
        """List of features that are contrastive in the loaded inventory."""
        if self._contrastive_features is None:
            self._contrastive_features = [
                f
                for f in self.features
                if self.plus_segs[f] and self.minus_segs[f]
            ]
        return self._contrastive_features

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
    ) -> tuple[bool, list[dict[str, str]]]:
        """Return ``(is_natural_class, minimal_bundles)``; bundles is [] when False."""
        bundles = self.find_all_minimal_bundles(segments)
        return (True, bundles) if bundles else (False, [])

    def segment_distance(self, seg1: str, seg2: str) -> int:
        """Number of features whose values differ between two segments.

        '0' counts as different from '+' or '-'.
        """
        self._validate_segment(seg1)
        self._validate_segment(seg2)
        t1 = self._seg_value_tuples[seg1]
        t2 = self._seg_value_tuples[seg2]
        return sum(1 for a, b in zip(t1, t2) if a != b)

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

    def get_feature_distribution(self, feature: str) -> dict[str, int]:
        """Counts of '+', '-', and '0' for ``feature`` across the inventory."""
        self._validate_feature(feature)
        distribution: dict[str, int] = {"+": 0, "-": 0, "0": 0}
        for segment in self.segments.values():
            distribution[segment.get(feature, "0")] += 1
        return distribution

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
                    total += sum(1 for a, b in zip(ti, tj) if a != b)
            count = n * (n - 1) // 2
            stats["avg_feature_distance"] = total / count
        else:
            stats["avg_feature_distance"] = 0.0
        return stats

    def export_inventory(self, filepath: str) -> None:
        """Atomically write the current inventory to ``filepath`` as
        JSON. See ``Inventory.write_atomic`` for the durability
        guarantee."""
        self._inventory.write_atomic(filepath)
