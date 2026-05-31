"""Feature geometry inference.

Identifies parent-child dependencies (for example [nasal] requires
[+consonantal]) and sibling groupings, with confidence levels derived
from coverage thresholds and a hypergeometric significance test.
"""

from __future__ import annotations

from collections import defaultdict
from math import comb
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from phonology_engine.feature_engine import FeatureEngine


def _hypergeom_sf(k: int, n: int, big_k: int, m: int) -> float:
    """Right-tail ``P(X >= k)`` for ``X ~ Hypergeometric(n, big_k, m)``."""
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
    """Node in an inferred feature-geometry tree."""

    def __init__(self, feature: str, parent: GeometryNode | None = None):
        self.feature = feature
        self.parent = parent
        self.children: list[GeometryNode] = []
        self.siblings: list[GeometryNode] = []
        self.confidence = "low"
        self.coverage = 0.0
        self.p_value = 1.0

    def _add_child(self, child: GeometryNode) -> None:
        child.parent = self
        self.children.append(child)

    def _add_sibling(self, sibling: GeometryNode) -> None:
        if sibling not in self.siblings:
            self.siblings.append(sibling)
        if self not in sibling.siblings:
            sibling.siblings.append(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "p_value": self.p_value,
            "children": [child.to_dict() for child in self.children],
            "siblings": [sib.feature for sib in self.siblings],
        }


class GeometryAnalyzer:
    """Infer hierarchical feature geometry from a loaded inventory.

    Dependencies must pass two tests: a coverage threshold (how often
    the implication holds) and a hypergeometric significance test. A
    high-confidence dependency satisfies BOTH.
    """

    HIGH_COVERAGE_THRESHOLD = 0.90
    MODERATE_COVERAGE_THRESHOLD = 0.75
    SIGNIFICANCE_LEVEL = 0.05

    def __init__(self, engine: FeatureEngine) -> None:
        self.engine = engine
        self.dependencies: dict[str, Any] = {}
        self.geometry_tree: GeometryNode | None = None

    def analyze(self) -> GeometryNode:
        """Run dependency inference and return the root node.

        Resets ``dependencies`` and ``geometry_tree`` first so calling
        ``analyze`` twice on the same analyzer produces a clean run.
        Previously a second call left stale entries from the first.
        """
        self.dependencies = {}
        self.geometry_tree = None
        self._compute_dependencies()
        self.geometry_tree = self._build_tree()
        return self.geometry_tree

    def _compute_dependencies(self) -> None:
        features = self.engine.get_contrastive_features()
        for i, child_feat in enumerate(features):
            best_parent = None
            best_coverage = 0.0
            best_p_value = 1.0
            for j, parent_feat in enumerate(features):
                if i == j:
                    continue
                coverage = self._compute_coverage(parent_feat, child_feat)
                if coverage > best_coverage:
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
        """Fraction of segs where ``child`` specified implies ``parent``
        specified."""
        spec = self.engine.spec_segs
        spec_child = spec[child_feat]
        if not spec_child:
            return 0.0
        return len(spec_child & spec[parent_feat]) / len(spec_child)

    def _permutation_test(
        self, parent_feat: str, child_feat: str, observed_coverage: float
    ) -> float:
        """Hypergeometric one-sided p-value for the observed coverage.

        Under the null (random reassignment of child labels), the count
        of segments where both parent and child are specified follows
        ``Hypergeometric(N, K, M)`` with ``N`` = total segments,
        ``K`` = parent-specified segments, ``M`` = child-specified
        segments. Closed form replaces the prior 1000-iteration Monte
        Carlo test; eliminates sampling noise and runs ~1000x faster.
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
        nodes = {
            feature: GeometryNode(feature) for feature in self.engine.features
        }
        root_candidates = set(self.engine.features)
        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info["parent"]
            coverage = dep_info["coverage"]
            p_value = dep_info["p_value"]
            child_node = nodes[child_feat]
            parent_node = nodes[parent_feat]
            parent_node._add_child(child_node)
            child_node.coverage = coverage
            child_node.p_value = p_value
            if (
                coverage >= self.HIGH_COVERAGE_THRESHOLD
                and p_value < self.SIGNIFICANCE_LEVEL
            ):
                child_node.confidence = "high"
            elif coverage >= self.MODERATE_COVERAGE_THRESHOLD:
                child_node.confidence = "medium"
            else:
                child_node.confidence = "low"
            self.dependencies[child_feat]["confidence"] = child_node.confidence
            root_candidates.discard(child_feat)
        parent_to_children = defaultdict(list)
        for child_feat, dep_info in self.dependencies.items():
            parent_to_children[dep_info["parent"]].append(child_feat)
        for children in parent_to_children.values():
            if len(children) > 1:
                for i, child1 in enumerate(children):
                    for child2 in children[i + 1 :]:
                        nodes[child1]._add_sibling(nodes[child2])
        # Sort root candidates for deterministic tree order across runs
        # (set iteration is hash-randomized).
        if len(root_candidates) == 0:
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

    def get_dependency_summary(self) -> list[dict[str, Any]]:
        """Discovered dependencies sorted by confidence, then coverage."""
        summary = [
            {
                "child": child_feat,
                "parent": dep_info["parent"],
                "coverage": dep_info["coverage"],
                "p_value": dep_info["p_value"],
                "confidence": dep_info["confidence"],
            }
            for child_feat, dep_info in self.dependencies.items()
        ]
        confidence_order = {"high": 0, "medium": 1, "low": 2}
        summary.sort(
            key=lambda x: (confidence_order[x["confidence"]], -x["coverage"])
        )
        return summary
