"""Feature geometry inference for phonological hierarchies.

Identifies parent-child dependencies (e.g., [nasal] requires
[+consonantal]) and sibling groupings (features that co-occur at the
same level), with confidence levels based on coverage and permutation
testing.
"""

from __future__ import annotations

from collections import defaultdict
from math import comb
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phonology_features.engine.feature_engine import FeatureEngine


def _hypergeom_sf(k: int, n: int, big_k: int, m: int) -> float:
    """Right-tail survival function: P(X >= k) for
    X ~ Hypergeometric(n, big_k, m).

    Args:
        n: population size.
        big_k: successes in the population.
        m: sample size.
        k: threshold (return probability of meeting or exceeding it).
    """
    if k <= 0:
        return 1.0
    upper = min(m, big_k)
    if k > upper:
        return 0.0
    total = comb(n, m)
    tail = sum(
        comb(big_k, x) * comb(n - big_k, m - x) for x in range(k, upper + 1)
    )
    return tail / total


class GeometryNode:
    """Represents a node in a feature geometry tree."""

    def __init__(self, feature: str, parent: GeometryNode | None = None):
        """
        Initialize a geometry node.

        Args:
            feature: Feature name
            parent: Parent node (None for root)
        """
        self.feature = feature
        self.parent = parent
        self.children: list[GeometryNode] = []
        self.siblings: list[GeometryNode] = []  # Features at the same level
        self.confidence = "low"  # "high", "moderate", or "low"
        self.coverage = 0.0  # Proportion of segments where dependency holds
        self.p_value = 1.0  # Permutation test p-value

    def _add_child(self, child: GeometryNode) -> None:
        """Add a child node."""
        child.parent = self
        self.children.append(child)

    def _add_sibling(self, sibling: GeometryNode) -> None:
        """Add a sibling node (mutual relationship)."""
        if sibling not in self.siblings:
            self.siblings.append(sibling)
        if self not in sibling.siblings:
            sibling.siblings.append(self)

    def to_dict(self) -> dict:
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
    SIGNIFICANCE_LEVEL = 0.05

    def __init__(self, engine: FeatureEngine) -> None:
        """
        Initialize the geometry analyzer.

        Args:
            engine: FeatureEngine instance with loaded inventory
        """
        self.engine = engine
        # feature -> {parent, coverage, p_value, confidence}
        self.dependencies: dict = {}
        self.geometry_tree: GeometryNode | None = None

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
                # Test if child_feat depends on parent_feat: if child is
                # specified (+/-), parent must also be specified
                coverage = self._compute_coverage(parent_feat, child_feat)
                if coverage > best_coverage:
                    # Run permutation test (pass coverage to avoid recomputing it)
                    p_value = self._permutation_test(
                        parent_feat, child_feat, coverage
                    )
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
        spec = self.engine.spec_segs
        spec_child = spec[child_feat]
        if not spec_child:
            return 0.0
        return len(spec_child & spec[parent_feat]) / len(spec_child)

    def _permutation_test(
        self, parent_feat: str, child_feat: str, observed_coverage: float
    ) -> float:
        """
        Compute dependency significance via the hypergeometric distribution.

        Under the null (random reassignment of child labels across segments),
        the count of segments where both parent and child are specified is
        distributed Hypergeometric(N, K, M):

            N: total segments
            K: segments where the parent is specified
            M: segments where the child is specified  (= "applicable")

        The p-value is the right-tail probability that the count meets or
        exceeds the observed value, computed in closed form. This replaces
        the prior 1000-iteration Monte Carlo permutation test, eliminating
        sampling noise while running ~3 orders of magnitude faster.

        Args:
            parent_feat: Proposed parent feature
            child_feat: Proposed child feature
            observed_coverage: Coverage as returned by ``_compute_coverage``;
                used only to handle the degenerate ``applicable == 0`` case.

        Returns:
            One-sided p-value in [0.0, 1.0].
        """
        spec = self.engine.spec_segs
        n = len(self.engine.segments)
        spec_child = spec[child_feat]
        applicable = len(spec_child)
        if applicable == 0:
            return 1.0 if observed_coverage <= 0.0 else 0.0
        spec_parent = spec[parent_feat]
        k = len(spec_parent)
        if k == 0:
            return 1.0
        observed_holds = len(spec_child & spec_parent)
        return _hypergeom_sf(observed_holds, n, k, applicable)

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
            parent_node._add_child(child_node)
            # Set confidence level once; store in dep_info to avoid recomputing.
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
            self.dependencies[child_feat]["confidence"] = child_node.confidence
            # Remove from root candidates
            root_candidates.discard(child_feat)
        # Identify sibling groups (features with same parent)
        parent_to_children = defaultdict(list)
        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info["parent"]
            parent_to_children[parent_feat].append(child_feat)
        for children in parent_to_children.values():
            if len(children) > 1:
                for i, child1 in enumerate(children):
                    for child2 in children[i + 1 :]:
                        nodes[child1]._add_sibling(nodes[child2])
        # Create artificial root if multiple roots exist. ``root_candidates``
        # is a set, so its iteration order would otherwise vary across
        # runs (Python's hash randomization). Sort before adding so the
        # tree's child order is deterministic.
        if len(root_candidates) == 0:
            # Shouldn't happen, but handle gracefully
            root = GeometryNode("ROOT")
            for node in nodes.values():
                if node.parent is None:
                    root._add_child(node)
        elif len(root_candidates) == 1:
            root = nodes[next(iter(root_candidates))]
        else:
            root = GeometryNode("ROOT")
            for feat in sorted(root_candidates):
                root._add_child(nodes[feat])
        return root

    def get_dependency_summary(self) -> list[dict]:
        """
        Get a summary of all discovered dependencies.

        Returns:
            List of dependency dicts with child, parent, coverage,
            p_value, confidence keys.
        """
        summary = []
        for child_feat, dep_info in self.dependencies.items():
            summary.append(
                {
                    "child": child_feat,
                    "parent": dep_info["parent"],
                    "coverage": dep_info["coverage"],
                    "p_value": dep_info["p_value"],
                    "confidence": dep_info["confidence"],
                }
            )
        # Sort by confidence, then coverage
        confidence_order = {"high": 0, "moderate": 1, "low": 2}
        summary.sort(
            key=lambda x: (confidence_order[x["confidence"]], -x["coverage"])
        )
        return summary

    def export_tree(self) -> dict:
        """
        Export the geometry tree as a nested dictionary.

        Returns:
            Dictionary representation of the tree
        """
        tree = (
            self.geometry_tree
            if self.geometry_tree is not None
            else self.analyze()
        )
        return tree.to_dict()

    def get_path_to_root(self, feature: str) -> list[str]:
        """
        Get the path from a feature to the root of the tree.

        Args:
            feature: Feature name

        Returns:
            List of feature names from the given feature to root
        """
        tree = (
            self.geometry_tree
            if self.geometry_tree is not None
            else self.analyze()
        )

        # Find the node
        def find_node(node: GeometryNode, target: str) -> GeometryNode | None:
            if node.feature == target:
                return node
            for child in node.children:
                result = find_node(child, target)
                if result is not None:
                    return result
            return None

        node = find_node(tree, feature)
        if node is None:
            return []
        path = []
        current: GeometryNode | None = node
        while current is not None:
            path.append(current.feature)
            current = current.parent
        return path
