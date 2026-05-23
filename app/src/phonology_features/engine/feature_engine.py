"""
Core phonology engine for segment and feature analysis.

This module provides the foundational logic for phonological analysis:
- Segment lookup and matching
- Natural class computation
- Feature value queries
- Contrastiveness checking
- Segment distance calculation

All phonological logic is independent of the GUI and can be used in scripts.
"""

import json

_VALID_VALUES = {"+", "-", "0"}


class FeatureEngine:
    """
    Main engine for phonological segment and feature analysis.

    Manages a single inventory at a time, providing operations for:
    - Loading inventories from JSON
    - Querying segments by features
    - Computing natural classes
    - Analyzing feature contrasts
    - Calculating phonological distances
    """

    def __init__(self) -> None:
        """Initialize an empty feature engine."""
        self.metadata: dict = {}
        self.features: list[str] = []
        self.segments: dict[str, dict[str, str]] = {}
        # Per-feature segment-set caches, populated by ``_rebuild_caches``
        # after every ``load_inventory``. Treat as read-only: mutating
        # ``segments`` directly without a reload will desync these.
        self.spec_segs: dict[str, frozenset[str]] = {}
        self.plus_segs: dict[str, frozenset[str]] = {}
        self.minus_segs: dict[str, frozenset[str]] = {}
        # seg -> tuple of feature values in ``self.features`` order. Used
        # for fast pairwise comparisons (avg distance, neighbor search).
        self._seg_value_tuples: dict[str, tuple[str, ...]] = {}
        self._contrastive_features: list[str] | None = None

    # Private helpers
    def _validate_segment(self, segment: str) -> None:
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not found in inventory")

    def _validate_feature(self, feature: str) -> None:
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not found in inventory")

    @staticmethod
    def _feat_match(seg_val: str, spec_val: str) -> bool:
        """True if a segment's feature value matches a spec value.

        Underspecified ("0") in the segment is compatible with any spec.
        """
        return seg_val == spec_val or seg_val == "0"

    def _find_segments_unsorted(
        self,
        feature_spec: dict[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """Match segments against a feature spec without sorting.

        If underspec_compatible is True, underspecified ("0") in a segment
        is treated as compatible with any spec value.  Used for natural
        class analysis.  Default (False) requires exact value match.
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

    # Public API
    def load_inventory(self, filepath: str) -> None:
        """
        Load a phonological inventory from JSON file.

        Args:
            filepath: Path to JSON inventory file

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON structure or values are invalid
        """
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        self.load_inventory_data(data)

    def load_inventory_data(self, data: dict) -> None:
        """Load from an already-parsed inventory dict.

        Use this when the caller already parsed the JSON (e.g. so the
        validator and the engine can share one parse). Same validation
        and ``_rebuild_caches`` behavior as ``load_inventory``.
        """
        if "features" not in data or "segments" not in data:
            raise ValueError(
                "Inventory must contain 'features' and 'segments' fields"
            )
        if not isinstance(data["features"], list) or not all(
            isinstance(f, str) for f in data["features"]
        ):
            raise ValueError("'features' must be a list of strings")
        if len(data["features"]) != len(set(data["features"])):
            raise ValueError("'features' list contains duplicate names")
        if not isinstance(data["segments"], dict):
            raise ValueError("'segments' must be a dictionary")
        for seg_name, seg_feats in data["segments"].items():
            if not isinstance(seg_feats, dict):
                raise ValueError(
                    f"Segment '{seg_name}' feature bundle must be a dictionary"
                )
            for feat_name, feat_val in seg_feats.items():
                if feat_val not in _VALID_VALUES:
                    raise ValueError(
                        f"Segment '{seg_name}' feature '{feat_name}'"
                        f" has invalid value '{feat_val}'"
                        f" (expected one of {sorted(_VALID_VALUES)})"
                    )
        self.metadata = data.get("metadata", {})
        self.features = data["features"]
        self.segments = data["segments"]
        self._rebuild_caches()

    def _rebuild_caches(self) -> None:
        """Rebuild derived per-feature segment-set caches and segment value
        tuples. Called from ``load_inventory_data`` (and its file-IO
        wrapper ``load_inventory``). The engine has no public setter
        API; reloading is the only path to mutate ``self.segments``,
        and both entry points call this on completion.
        """
        spec: dict[str, set[str]] = {f: set() for f in self.features}
        plus: dict[str, set[str]] = {f: set() for f in self.features}
        minus: dict[str, set[str]] = {f: set() for f in self.features}
        for seg, feats in self.segments.items():
            for f in self.features:
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
            seg: tuple(feats.get(f, "0") for f in self.features)
            for seg, feats in self.segments.items()
        }
        self._contrastive_features = None

    def get_segment_features(self, segment: str) -> dict[str, str]:
        """
        Get the complete feature specification for a segment.

        Args:
            segment: Segment symbol (e.g. "p", "b", "m")

        Returns:
            Dictionary mapping feature names to values ("+", "-", "0").
            Features absent from the segment's entry are returned as "0".

        Raises:
            KeyError: If segment not in inventory
        """
        self._validate_segment(segment)
        return {f: self.segments[segment].get(f, "0") for f in self.features}

    def get_feature_value(self, segment: str, feature: str) -> str:
        """
        Get the value of a specific feature for a segment.

        Args:
            segment: Segment symbol
            feature: Feature name

        Returns:
            Feature value: "+", "-", or "0"

        Raises:
            KeyError: If segment or feature not found
        """
        self._validate_segment(segment)
        self._validate_feature(feature)
        return self.segments[segment].get(feature, "0")

    def find_segments(
        self,
        feature_spec: dict[str, str],
        *,
        underspec_compatible: bool = False,
    ) -> list[str]:
        """
        Find all segments matching a feature specification.

        Partial specifications are supported; only the specified features
        need to match.

        Args:
            feature_spec: Dictionary of feature:value pairs to match
            underspec_compatible: If True, segments with "0" for a feature
                are treated as compatible with any spec value.  Useful for
                natural class analysis.

        Returns:
            Sorted list of segment symbols matching the specification

        Raises:
            KeyError: If any feature in feature_spec is not in the inventory
            ValueError: If any value in feature_spec is not "+", "-", or "0"
        """
        for feature, value in feature_spec.items():
            self._validate_feature(feature)
            if value not in _VALID_VALUES:
                raise ValueError(
                    f"Invalid feature value '{value}' for '{feature}'"
                )
        return sorted(
            self._find_segments_unsorted(
                feature_spec, underspec_compatible=underspec_compatible
            )
        )

    def find_all_minimal_bundles(
        self, segments: list[str]
    ) -> list[dict[str, str]]:
        """
        Find every minimal feature bundle that uniquely characterizes a segment set.

        A bundle B characterizes S when
        ``find_segments(B, underspec_compatible=True) == S``.
        This method returns ALL bundles of the smallest possible size,
        not just one greedy solution.

        Algorithm (hitting-set backtracking):
          1. Collect candidate features; those with a constant value across S.
          2. For each segment outside S, record which candidates can exclude it
             (i.e., have a different value than S's value for that feature).
          3. Backtrack over subsets of candidates, pruning aggressively:
             - depth >= best size found so far
             - remaining candidates cannot cover an uncovered outside segment
          4. Return all subsets that hit every outside segment.

        Args:
            segments: List of segment symbols

        Returns:
            All minimal feature bundles as a list of {feature: value} dicts.
            Returns [{}] for a universal class (S == all segments).
            Returns [] if S cannot be uniquely characterised.

        Raises:
            ValueError: If any segment is not in the inventory
        """
        if not segments:
            return [{}]
        for seg in segments:
            if seg not in self.segments:
                raise ValueError(f"Segment '{seg}' not in inventory")
        segment_set = set(segments)
        # Features whose non-zero values agree across every target segment.
        # Underspecified ("0") is compatible with any value.
        candidates: dict[str, str] = {}
        for feature in self.features:
            values = {self.segments[seg].get(feature, "0") for seg in segments}
            specified = values - {"0"}
            if len(specified) == 1:
                candidates[feature] = specified.pop()
            elif len(specified) == 0 and "0" in values:
                pass  # all underspecified; not a useful candidate
        # Segments outside the target set that must be excluded
        outside = [s for s in self.segments if s not in segment_set]
        # Universal class; S is the entire inventory
        if not outside:
            return [{}]
        # For each outside segment, which candidates exclude it?
        # A candidate excludes an outside segment when the segment has a
        # non-zero value that differs from the candidate value.
        # If the outside segment is underspecified (0), it's compatible.
        excluders: list[set[str]] = []
        for seg in outside:
            exc: set[str] = {
                feat
                for feat, val in candidates.items()
                if not self._feat_match(self.segments[seg].get(feat, "0"), val)
            }
            if not exc:
                return (
                    []
                )  # This segment cannot be excluded -> not a natural class
            excluders.append(exc)
        # Sort candidates by descending coverage (hits the most outside segments first)
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
        ) -> None:
            nonlocal best_size
            # All outside segments are excluded; record solution
            if all(exc & chosen_set for exc in excluders):
                k = len(chosen)
                if best_size is None or k < best_size:
                    best_size = k
                    results.clear()
                    results.append({f: candidates[f] for f in chosen})
                elif k == best_size:
                    results.append({f: candidates[f] for f in chosen})
                return
            # Prune: already at or past the best depth
            if best_size is not None and len(chosen) >= best_size:
                return
            if idx >= n:
                return
            # Prune: remaining candidates cannot cover every uncovered outside segment
            remaining = set(candidate_list[idx:])
            if not all(
                (exc & chosen_set) or (exc & remaining) for exc in excluders
            ):
                return
            f = candidate_list[idx]
            # Branch A: include f
            backtrack(idx + 1, [*chosen, f], chosen_set | {f})
            # Branch B: exclude f; only if remaining can still cover everything
            remaining_without = set(candidate_list[idx + 1 :])
            if all(
                (exc & chosen_set) or (exc & remaining_without)
                for exc in excluders
            ):
                backtrack(idx + 1, chosen, chosen_set)

        backtrack(0, [], set())
        return results

    def compute_natural_class(self, segments: list[str]) -> dict[str, str]:
        """
        Return one minimal feature bundle characterising the segment set.

        Delegates to find_all_minimal_bundles and returns the first result.
        Use find_all_minimal_bundles directly when all solutions are needed.

        Note on ambiguous return: an empty dict ``{}`` is returned in two
        distinct situations:
          1. ``segments`` is empty OR equals the entire inventory (the
             "universal class"). The empty bundle correctly characterises
             every segment.
          2. The set is NOT a natural class. No bundle exists.
        Callers that need to distinguish these should use
        ``is_natural_class`` (returns ``(bool, [bundles])``) instead.

        Args:
            segments: List of segment symbols

        Returns:
            One minimal feature bundle, or {} (see ambiguity note above).

        Raises:
            ValueError: If any segment is not in the inventory
        """
        bundles = self.find_all_minimal_bundles(segments)
        return bundles[0] if bundles else {}

    def is_contrastive(self, feature: str) -> bool:
        """
        Check if a feature is contrastive in the inventory.

        A feature is contrastive if it takes both + and - values across
        at least some segments (ignoring inapplicable "0" values).

        Args:
            feature: Feature name

        Returns:
            True if feature is contrastive, False if invariant

        Raises:
            KeyError: If feature not in inventory
        """
        self._validate_feature(feature)
        return bool(self.plus_segs[feature]) and bool(self.minus_segs[feature])

    def get_contrastive_features(self) -> list[str]:
        """
        Get list of all contrastive features in the inventory.

        Returns:
            List of feature names that are contrastive
        """
        if self._contrastive_features is None:
            self._contrastive_features = [
                f
                for f in self.features
                if self.plus_segs[f] and self.minus_segs[f]
            ]
        return self._contrastive_features

    def common_features(self, segments: list[str]) -> dict[str, str]:
        """
        Get features with a shared +/- value across all given segments.

        Args:
            segments: List of segment symbols

        Returns:
            Dict mapping feature names to their shared value ('+' or '-')

        Raises:
            KeyError: If any segment is not in the inventory
        """
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
        """
        Check whether a set of segments forms a natural class in this inventory.

        A set is a natural class if there exists a conjunctive feature bundle
        whose extension equals exactly the given set.

        Args:
            segments: List of segment symbols

        Returns:
            Tuple of (is_natural_class, minimal_specifications).
            minimal_specifications is a list of all minimal bundles when True,
            or an empty list when False.
        """
        bundles = self.find_all_minimal_bundles(segments)
        return (True, bundles) if bundles else (False, [])

    def segment_distance(self, seg1: str, seg2: str) -> int:
        """
        Compute phonological distance between two segments.

        Distance is the number of features with different values.
        Inapplicable features ("0") count as different from + or -.

        Args:
            seg1: First segment symbol
            seg2: Second segment symbol

        Returns:
            Number of differing features

        Raises:
            KeyError: If either segment not in inventory
        """
        self._validate_segment(seg1)
        self._validate_segment(seg2)
        t1 = self._seg_value_tuples[seg1]
        t2 = self._seg_value_tuples[seg2]
        return sum(1 for a, b in zip(t1, t2) if a != b)

    def find_nearest_segments(
        self, segment: str, n: int = 5
    ) -> list[tuple[str, int]]:
        """
        Find the nearest segments to a given segment by feature distance.

        Args:
            segment: Target segment symbol
            n: Number of nearest neighbors to return

        Returns:
            List of (segment, distance) tuples, sorted by distance

        Raises:
            KeyError: If segment not in inventory
        """
        self._validate_segment(segment)
        distances = [
            (other, self.segment_distance(segment, other))
            for other in self.segments
            if other != segment
        ]
        distances.sort(key=lambda x: (x[1], x[0]))
        return distances[:n]

    def get_feature_distribution(self, feature: str) -> dict[str, int]:
        """
        Get the distribution of values for a feature across the inventory.

        Args:
            feature: Feature name

        Returns:
            Dictionary mapping values ("+", "-", "0") to counts

        Raises:
            KeyError: If feature not in inventory
        """
        self._validate_feature(feature)
        distribution: dict[str, int] = {"+": 0, "-": 0, "0": 0}
        for segment in self.segments.values():
            distribution[segment.get(feature, "0")] += 1
        return distribution

    def get_inventory_stats(self) -> dict[str, int | float | str]:
        """
        Get summary statistics about the loaded inventory.

        Returns:
            Dictionary with inventory statistics:
            - name: Inventory name
            - segment_count: Number of segments
            - feature_count: Number of features
            - contrastive_features: Number of contrastive features
            - avg_feature_distance: Average pairwise distance
        """
        stats: dict[str, int | float | str] = {
            "name": self.metadata.get("name", "Unknown"),
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
        """
        Export the current inventory to a JSON file.

        Args:
            filepath: Output file path
        """
        data = {
            "metadata": self.metadata,
            "features": self.features,
            "segments": self.segments,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
