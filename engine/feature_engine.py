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
from typing import Dict, List, Tuple, Union

import numpy as np


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

    # Feature value encoding for internal computation
    FEATURE_ENCODING = {"+": 1, "-": -1, "0": 0}
    FEATURE_DECODING = {1: "+", -1: "-", 0: "0"}

    def __init__(self):
        """Initialize an empty feature engine."""
        self.metadata = {}
        self.features = []
        self.segments = {}
        self._segment_matrix = None  # numpy array for efficient computation
        self._segment_order = []  # segment symbols in matrix order

    def load_inventory(self, filepath: str) -> None:
        """
        Load a phonological inventory from JSON file.

        Args:
            filepath: Path to JSON inventory file

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON format is invalid
        """
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Validate required fields
        if "features" not in data or "segments" not in data:
            raise ValueError(
                "Inventory must contain 'features' and 'segments' fields"
            )

        self.metadata = data.get("metadata", {})
        self.features = data["features"]
        self.segments = data["segments"]

        # Build internal numpy matrix for efficient computation
        self._build_segment_matrix()

    def _build_segment_matrix(self) -> None:
        """Build internal numpy matrix representation of segments."""
        self._segment_order = sorted(self.segments.keys())
        n_segments = len(self._segment_order)
        n_features = len(self.features)

        self._segment_matrix = np.zeros(
            (n_segments, n_features), dtype=np.int8
        )

        for i, segment in enumerate(self._segment_order):
            for j, feature in enumerate(self.features):
                value = self.segments[segment].get(feature, "0")
                self._segment_matrix[i, j] = self.FEATURE_ENCODING[value]

    def get_segment_features(self, segment: str) -> Dict[str, str]:
        """
        Get the complete feature specification for a segment.

        Args:
            segment: Segment symbol (e.g. "p", "b", "m")

        Returns:
            Dictionary mapping feature names to values ("+", "-", "0")
            Missing features are filled in with "0" (inapplicable)

        Raises:
            KeyError: If segment not in inventory
        """
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not found in inventory")

        # Return complete feature specification with missing features as "0"
        result = {}
        for feature in self.features:
            result[feature] = self.segments[segment].get(feature, "0")
        return result

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
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not found in inventory")
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not found in inventory")
        return self.segments[segment].get(feature, "0")

    def find_segments(self, feature_spec: Dict[str, str]) -> List[str]:
        """
        Find all segments matching a feature specification.

        Partial specifications are supported - only the specified features
        need to match. Inapplicable features ("0") are treated specially:
        a query with feature=0 matches only segments with 0 for that feature.

        Args:
            feature_spec: Dictionary of feature:value pairs to match

        Returns:
            List of segment symbols matching the specification
        """
        matching = []

        for segment, features in self.segments.items():
            match = True
            for feature, value in feature_spec.items():
                if features.get(feature, "0") != value:
                    match = False
                    break
            if match:
                matching.append(segment)

        return sorted(matching)

    def compute_natural_class(
        self, segments: List[str]
    ) -> Tuple[Dict[str, str], bool]:
        """
        Compute the minimal feature bundle that characterizes a set of segments.

        A natural class is characterized by the smallest set of features that
        picks out exactly the given segments and no others.

        Args:
            segments: List of segment symbols

        Returns:
            Tuple of (feature_bundle, is_minimal)
            - feature_bundle: Dict of features that characterize the class
            - is_minimal: True if no feature can be removed without expanding the class

        Raises:
            ValueError: If any segment not in inventory
        """
        for seg in segments:
            if seg not in self.segments:
                raise ValueError(f"Segment '{seg}' not in inventory")

        if not segments:
            return ({}, True)

        segment_set = set(segments)

        # Find features that are constant across the target segments
        candidate_features = {}

        for feature in self.features:
            values = set()

            for seg in segments:
                val = self.segments[seg].get(feature, "0")
                values.add(val)

            # Feature is a candidate ONLY if all segments have the exact same value
            # This ensures the bundle will match exactly these segments
            if len(values) == 1:
                candidate_features[feature] = values.pop()

        # Find minimal bundle - remove features one at a time and check if class expands
        minimal_bundle = candidate_features.copy()
        is_minimal = True

        for feature in candidate_features:
            test_bundle = {
                k: v for k, v in minimal_bundle.items() if k != feature
            }
            matches = set(self.find_segments(test_bundle))

            if matches == segment_set:
                # This feature is redundant
                del minimal_bundle[feature]
                is_minimal = False

        return (minimal_bundle, is_minimal)

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
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not in inventory")

        values = set()
        for segment in self.segments.values():
            val = segment.get(feature, "0")
            if val != "0":
                values.add(val)

        return len(values) > 1

    def get_contrastive_features(self) -> List[str]:
        """
        Get list of all contrastive features in the inventory.

        Returns:
            List of feature names that are contrastive
        """
        return [f for f in self.features if self.is_contrastive(f)]

    def common_features(self, segments: List[str]) -> Dict[str, str]:
        """
        Get features with a shared +/- value across all given segments.

        Args:
            segments: List of segment symbols

        Returns:
            Dict mapping feature names to their shared value ('+' or '-')
        """
        if not segments:
            return {}
        result = {}
        for feature in self.features:
            values = {self.segments[seg].get(feature, "0") for seg in segments}
            if len(values) == 1:
                v = values.pop()
                if v != "0":
                    result[feature] = v
        return result

    def is_natural_class(
        self, segments: List[str]
    ) -> Tuple[bool, Dict[str, str]]:
        """
        Check whether a set of segments forms a natural class.

        Args:
            segments: List of segment symbols

        Returns:
            Tuple of (is_natural_class, minimal_specification).
            minimal_specification is populated only when True.
        """
        bundle, _ = self.compute_natural_class(segments)
        found = set(self.find_segments(bundle))
        is_nc = found == set(segments)
        return is_nc, bundle if is_nc else {}

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
        if seg1 not in self.segments:
            raise KeyError(f"Segment '{seg1}' not in inventory")
        if seg2 not in self.segments:
            raise KeyError(f"Segment '{seg2}' not in inventory")

        features1 = self.segments[seg1]
        features2 = self.segments[seg2]

        distance = 0
        for feature in self.features:
            val1 = features1.get(feature, "0")
            val2 = features2.get(feature, "0")
            if val1 != val2:
                distance += 1

        return distance

    def find_nearest_segments(
        self, segment: str, n: int = 5
    ) -> List[Tuple[str, int]]:
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
        if segment not in self.segments:
            raise KeyError(f"Segment '{segment}' not in inventory")

        distances = []
        for other in self.segments:
            if other != segment:
                dist = self.segment_distance(segment, other)
                distances.append((other, dist))

        distances.sort(
            key=lambda x: (x[1], x[0])
        )  # Sort by distance, then alphabetically
        return distances[:n]

    def get_feature_distribution(self, feature: str) -> Dict[str, int]:
        """
        Get the distribution of values for a feature across the inventory.

        Args:
            feature: Feature name

        Returns:
            Dictionary mapping values ("+", "-", "0") to counts

        Raises:
            KeyError: If feature not in inventory
        """
        if feature not in self.features:
            raise KeyError(f"Feature '{feature}' not in inventory")

        distribution = {"+": 0, "-": 0, "0": 0}
        for segment in self.segments.values():
            val = segment.get(feature, "0")
            distribution[val] += 1

        return distribution

    def get_inventory_stats(self) -> Dict[str, Union[int, float, str]]:
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
        stats = {
            "name": self.metadata.get("name", "Unknown"),
            "segment_count": len(self.segments),
            "feature_count": len(self.features),
            "contrastive_features": len(self.get_contrastive_features()),
        }

        # Compute average pairwise distance
        if len(self.segments) > 1:
            distances = []
            segments = list(self.segments.keys())
            for i in range(len(segments)):
                for j in range(i + 1, len(segments)):
                    distances.append(
                        self.segment_distance(segments[i], segments[j])
                    )
            stats["avg_feature_distance"] = np.mean(distances)
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
