"""
Feature geometry inference for phonological hierarchies.

This module analyzes feature dependencies and implicational relationships
to infer hierarchical feature geometry structures. Feature geometry is
the theory that phonological features are organized in a hierarchical
tree structure, where some features depend on or are licensed by others.

The analyzer uses statistical methods to identify:
- Parent-child dependencies (e.g., [nasal] requires [+consonantal])
- Sibling groupings (features that co-occur at the same level)
- Confidence levels based on coverage and permutation testing
"""

from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np


class GeometryNode:
    """Represents a node in a feature geometry tree."""

    def __init__(self, feature: str, parent: Optional["GeometryNode"] = None):
        """
        Initialize a geometry node.

        Args:
            feature: Feature name
            parent: Parent node (None for root)
        """
        self.feature = feature
        self.parent = parent
        self.children: List["GeometryNode"] = []
        self.siblings: List["GeometryNode"] = []  # Features at the same level
        self.confidence = "low"  # "high", "moderate", or "low"
        self.coverage = 0.0  # Proportion of segments where dependency holds
        self.p_value = 1.0  # Permutation test p-value

    def add_child(self, child: "GeometryNode") -> None:
        """Add a child node."""
        child.parent = self
        self.children.append(child)

    def add_sibling(self, sibling: "GeometryNode") -> None:
        """Add a sibling node (mutual relationship)."""
        if sibling not in self.siblings:
            self.siblings.append(sibling)
        if self not in sibling.siblings:
            sibling.siblings.append(self)

    def to_dict(self) -> Dict:
        """Convert node to dictionary representation."""
        return {
            "feature": self.feature,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "p_value": self.p_value,
            "children": [child.to_dict() for child in self.children],
            "siblings": [sib.feature for sib in self.siblings],
        }


class GeometryAnalyzer:
    """
    Analyzes feature dependencies and infers hierarchical geometry.

    The analyzer uses two main criteria for establishing dependencies:
    1. Coverage threshold: How often does the implication hold?
    2. Permutation test: Is the relationship statistically significant?

    A high-confidence dependency must satisfy BOTH criteria.
    """

    # Thresholds for confidence levels
    HIGH_COVERAGE_THRESHOLD = 0.90
    MODERATE_COVERAGE_THRESHOLD = 0.75
    PERMUTATION_ITERATIONS = 1000
    SIGNIFICANCE_LEVEL = 0.05

    def __init__(self, engine):
        """
        Initialize the geometry analyzer.

        Args:
            engine: FeatureEngine instance with loaded inventory
        """
        self.engine = engine
        self.dependencies = (
            {}
        )  # feature -> {parent: GeometryNode, coverage: float, p_value: float}
        self.geometry_tree = None

    def analyze(self) -> GeometryNode:
        """
        Perform full geometry analysis on the loaded inventory.

        Returns:
            Root node of the inferred feature geometry tree
        """
        # Build dependency matrix
        self._compute_dependencies()

        # Construct tree from dependencies
        self.geometry_tree = self._build_tree()

        return self.geometry_tree

    def _compute_dependencies(self) -> None:
        """Compute all pairwise feature dependencies."""
        features = self.engine.get_contrastive_features()

        for i, child_feat in enumerate(features):
            best_parent = None
            best_coverage = 0.0
            best_p_value = 1.0

            for j, parent_feat in enumerate(features):
                if i == j:
                    continue

                # Test if child_feat depends on parent_feat
                # Dependency means: if child is specified (+/-), parent must be specified
                coverage = self._compute_coverage(parent_feat, child_feat)

                if coverage > best_coverage:
                    # Run permutation test
                    p_value = self._permutation_test(parent_feat, child_feat)

                    if p_value < self.SIGNIFICANCE_LEVEL:
                        best_parent = parent_feat
                        best_coverage = coverage
                        best_p_value = p_value

            if best_parent is not None:
                self.dependencies[child_feat] = {
                    "parent": best_parent,
                    "coverage": best_coverage,
                    "p_value": best_p_value,
                }

    def _compute_coverage(self, parent_feat: str, child_feat: str) -> float:
        """
        Compute coverage of a dependency relationship.

        Coverage is the proportion of segments where:
        if child is specified (+/-), then parent is also specified (+/-)

        Args:
            parent_feat: Proposed parent feature
            child_feat: Proposed child feature

        Returns:
            Coverage ratio (0.0 to 1.0)
        """
        segments = self.engine.segments
        applicable_count = 0  # Segments where child is specified
        holds_count = 0  # Segments where dependency holds

        for segment, features in segments.items():
            child_val = features.get(child_feat, "0")
            parent_val = features.get(parent_feat, "0")

            if child_val != "0":
                applicable_count += 1
                if parent_val != "0":
                    holds_count += 1

        if applicable_count == 0:
            return 0.0

        return holds_count / applicable_count

    def _permutation_test(self, parent_feat: str, child_feat: str) -> float:
        """
        Perform permutation test for dependency significance.

        Randomly permute the child feature values and recompute coverage.
        P-value is the proportion of permutations with coverage >= observed.

        Args:
            parent_feat: Proposed parent feature
            child_feat: Proposed child feature

        Returns:
            P-value from permutation test
        """
        observed_coverage = self._compute_coverage(parent_feat, child_feat)

        # Get child feature values as array
        segments = list(self.engine.segments.keys())
        child_values = [
            self.engine.segments[s].get(child_feat, "0") for s in segments
        ]

        # Count permutations with coverage >= observed
        extreme_count = 0

        rng = np.random.RandomState(42)  # Fixed seed for reproducibility

        for _ in range(self.PERMUTATION_ITERATIONS):
            # Shuffle child values
            permuted = child_values.copy()
            rng.shuffle(permuted)

            # Temporarily replace values and compute coverage
            original_values = {}
            for i, seg in enumerate(segments):
                original_values[seg] = self.engine.segments[seg].get(
                    child_feat, "0"
                )
                self.engine.segments[seg][child_feat] = permuted[i]

            permuted_coverage = self._compute_coverage(parent_feat, child_feat)

            # Restore original values
            for seg in segments:
                self.engine.segments[seg][child_feat] = original_values[seg]

            if permuted_coverage >= observed_coverage:
                extreme_count += 1

        return extreme_count / self.PERMUTATION_ITERATIONS

    def _build_tree(self) -> GeometryNode:
        """
        Build tree structure from computed dependencies.

        Returns:
            Root node of the geometry tree
        """
        # Create nodes for all features
        nodes = {}
        for feature in self.engine.features:
            nodes[feature] = GeometryNode(feature)

        # Establish parent-child relationships
        root_candidates = set(self.engine.features)

        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info["parent"]
            coverage = dep_info["coverage"]
            p_value = dep_info["p_value"]

            child_node = nodes[child_feat]
            parent_node = nodes[parent_feat]

            parent_node.add_child(child_node)

            # Set confidence level
            child_node.coverage = coverage
            child_node.p_value = p_value

            if (
                coverage >= self.HIGH_COVERAGE_THRESHOLD
                and p_value < self.SIGNIFICANCE_LEVEL
            ):
                child_node.confidence = "high"
            elif coverage >= self.MODERATE_COVERAGE_THRESHOLD:
                child_node.confidence = "moderate"
            else:
                child_node.confidence = "low"

            # Remove from root candidates
            if child_feat in root_candidates:
                root_candidates.remove(child_feat)

        # Identify sibling groups (features with same parent)
        parent_to_children = defaultdict(list)
        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info["parent"]
            parent_to_children[parent_feat].append(child_feat)

        for parent_feat, children in parent_to_children.items():
            if len(children) > 1:
                for i, child1 in enumerate(children):
                    for child2 in children[i + 1 :]:
                        nodes[child1].add_sibling(nodes[child2])

        # Create artificial root if multiple roots exist
        if len(root_candidates) == 0:
            # Shouldn't happen, but handle gracefully
            root = GeometryNode("ROOT")
            for node in nodes.values():
                if node.parent is None:
                    root.add_child(node)
        elif len(root_candidates) == 1:
            root = nodes[list(root_candidates)[0]]
        else:
            root = GeometryNode("ROOT")
            for feat in root_candidates:
                root.add_child(nodes[feat])

        return root

    def get_dependency_summary(self) -> List[Dict]:
        """
        Get a summary of all discovered dependencies.

        Returns:
            List of dependency dictionaries with child, parent, coverage, p_value, confidence
        """
        summary = []

        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info["parent"]
            coverage = dep_info["coverage"]
            p_value = dep_info["p_value"]

            if (
                coverage >= self.HIGH_COVERAGE_THRESHOLD
                and p_value < self.SIGNIFICANCE_LEVEL
            ):
                confidence = "high"
            elif coverage >= self.MODERATE_COVERAGE_THRESHOLD:
                confidence = "moderate"
            else:
                confidence = "low"

            summary.append(
                {
                    "child": child_feat,
                    "parent": parent_feat,
                    "coverage": coverage,
                    "p_value": p_value,
                    "confidence": confidence,
                }
            )

        # Sort by confidence, then coverage
        confidence_order = {"high": 0, "moderate": 1, "low": 2}
        summary.sort(
            key=lambda x: (confidence_order[x["confidence"]], -x["coverage"])
        )

        return summary

    def export_tree(self) -> Dict:
        """
        Export the geometry tree as a nested dictionary.

        Returns:
            Dictionary representation of the tree
        """
        if self.geometry_tree is None:
            self.analyze()

        return self.geometry_tree.to_dict()

    def get_path_to_root(self, feature: str) -> List[str]:
        """
        Get the path from a feature to the root of the tree.

        Args:
            feature: Feature name

        Returns:
            List of feature names from the given feature to root
        """
        if self.geometry_tree is None:
            self.analyze()

        # Find the node
        def find_node(
            node: GeometryNode, target: str
        ) -> Optional[GeometryNode]:
            if node.feature == target:
                return node
            for child in node.children:
                result = find_node(child, target)
                if result is not None:
                    return result
            return None

        node = find_node(self.geometry_tree, feature)
        if node is None:
            return []

        path = []
        current: Optional[GeometryNode] = node
        while current is not None:
            path.append(current.feature)
            current = current.parent

        return path
