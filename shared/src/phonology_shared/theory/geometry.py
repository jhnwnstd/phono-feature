"""Feature geometry inference.

Infers an inventory-internal feature geometry from valued segment
feature data. The core inference is empirical: it estimates parent-child
dependencies from the loaded inventory rather than validating the
inventory against a fixed feature-geometry theory.

The analyzer currently infers specifiedness dependencies of the form
"child feature specified implies parent feature specified". It keeps the
legacy tree interface while also exposing structured edges with support,
violations, hypergeometric p-values, and optional Benjamini-Hochberg
q-values for multiple-testing control.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import comb
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import FeatureEngine


ConfidenceLabel = Literal["high", "medium", "low"]
GeometryRelation = Literal["specifiedness"]


def _hypergeom_sf(k: int, n: int, big_k: int, m: int) -> float:
    """Right-tail ``P(X >= k)`` for ``X ~ Hypergeometric(n, big_k, m)``.

    ``n`` is population size, ``big_k`` is the number of successes in
    the population, ``m`` is the sample size, and ``k`` is the observed
    number of successes in the sample.
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


def _benjamini_hochberg_q_values(
    p_values: Sequence[float],
) -> tuple[float, ...]:
    """Return Benjamini-Hochberg adjusted q-values.

    The returned tuple is in the same order as ``p_values`` and is
    monotone with respect to p-value rank.
    """
    m = len(p_values)
    if m == 0:
        return ()

    ranked = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * m
    running_min = 1.0

    for rank, (idx, p_value) in reversed(list(enumerate(ranked, start=1))):
        candidate = min(1.0, p_value * m / rank)
        running_min = min(running_min, candidate)
        adjusted[idx] = running_min

    return tuple(adjusted)


@dataclass(frozen=True, slots=True)
class GeometryInferenceConfig:
    """Thresholds and output-shaping policy for geometry inference."""

    high_coverage_threshold: float = 0.90
    moderate_coverage_threshold: float = 0.75
    significance_level: float = 0.05
    use_fdr: bool = True
    min_child_support: int = 2
    max_parents_per_child: int = 1


@dataclass(frozen=True, slots=True)
class GeometryEdge:
    """A candidate inferred relation between two features.

    ``coverage`` is the fraction of child-specified segments that also
    specify the parent. ``p_value`` tests whether the observed overlap is
    unexpectedly large under a hypergeometric null. ``q_value`` is the
    Benjamini-Hochberg adjusted p-value when FDR correction is enabled.
    """

    parent: str
    child: str
    relation: GeometryRelation
    coverage: float
    p_value: float
    q_value: float | None
    confidence: ConfidenceLabel
    supporting_segments: tuple[str, ...]
    violating_segments: tuple[str, ...]
    parent_only_segments: tuple[str, ...]

    @property
    def child_support(self) -> int:
        """Number of segments on which the child feature is specified."""
        return len(self.supporting_segments) + len(self.violating_segments)

    @property
    def score(self) -> tuple[float, float, float, str]:
        """Sort key for choosing a display parent.

        Higher coverage wins first. Lower adjusted significance wins
        second. More specific parents win third. The final string makes
        the result deterministic.
        """
        significance = (
            self.q_value if self.q_value is not None else self.p_value
        )
        specificity = 1.0 - (
            len(self.supporting_segments) + len(self.parent_only_segments)
        )
        return (self.coverage, -significance, specificity, self.parent)


@dataclass(frozen=True, slots=True)
class DependencyInfo:
    """Compatibility summary for the selected parent of one child."""

    parent: str
    coverage: float
    p_value: float
    q_value: float | None
    confidence: ConfidenceLabel
    supporting_segments: tuple[str, ...]
    violating_segments: tuple[str, ...]


class GeometryNode:
    """Node in an inferred feature-geometry tree."""

    def __init__(self, feature: str, parent: GeometryNode | None = None):
        self.feature = feature
        self.parent = parent
        self.children: list[GeometryNode] = []
        self.siblings: list[GeometryNode] = []
        self.confidence: ConfidenceLabel = "low"
        self.coverage = 0.0
        self.p_value = 1.0
        self.q_value: float | None = None

    def _add_child(self, child: GeometryNode) -> None:
        if child not in self.children:
            child.parent = self
            self.children.append(child)

    def _add_sibling(self, sibling: GeometryNode) -> None:
        if sibling is self:
            return
        if sibling not in self.siblings:
            self.siblings.append(sibling)
        if self not in sibling.siblings:
            sibling.siblings.append(self)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the tree defensively.

        Cycle detection is included even though the tree builder tries
        to prevent cycles. This keeps diagnostics safe on unusual input.
        """
        return self._to_dict(set())

    def _to_dict(self, seen: set[int]) -> dict[str, Any]:
        node_id = id(self)
        if node_id in seen:
            return {
                "feature": self.feature,
                "confidence": self.confidence,
                "coverage": self.coverage,
                "p_value": self.p_value,
                "q_value": self.q_value,
                "children": [],
                "siblings": sorted(sib.feature for sib in self.siblings),
                "cycle": True,
            }

        seen.add(node_id)
        return {
            "feature": self.feature,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "p_value": self.p_value,
            "q_value": self.q_value,
            "children": [child._to_dict(seen) for child in self.children],
            "siblings": sorted(sib.feature for sib in self.siblings),
        }


class GeometryAnalyzer:
    """Infer hierarchical feature geometry from a loaded inventory.

    The analyzer first builds structured dependency edges, then projects
    the strongest selected edges into a tree for legacy callers. The tree
    is a display view over the inferred graph, not the only analysis
    product.
    """

    HIGH_COVERAGE_THRESHOLD = 0.90
    MODERATE_COVERAGE_THRESHOLD = 0.75
    SIGNIFICANCE_LEVEL = 0.05

    def __init__(
        self,
        engine: FeatureEngine,
        config: GeometryInferenceConfig | None = None,
    ) -> None:
        self.engine = engine
        self.config = config or GeometryInferenceConfig(
            high_coverage_threshold=self.HIGH_COVERAGE_THRESHOLD,
            moderate_coverage_threshold=self.MODERATE_COVERAGE_THRESHOLD,
            significance_level=self.SIGNIFICANCE_LEVEL,
        )
        self.dependencies: dict[str, DependencyInfo] = {}
        self.all_edges: tuple[GeometryEdge, ...] = ()
        self.geometry_tree: GeometryNode | None = None

    def analyze(self) -> GeometryNode:
        """Run dependency inference and return the root node.

        Resets analysis state first so repeated calls on the same
        analyzer produce clean runs.
        """
        self.dependencies = {}
        self.all_edges = ()
        self.geometry_tree = None
        self._compute_dependencies()
        self.geometry_tree = self._build_tree()
        return self.geometry_tree

    def _compute_dependencies(self) -> None:
        edges = self._collect_specifiedness_edges()
        accepted = self._accepted_edges(edges)
        self.all_edges = tuple(accepted)

        by_child: dict[str, list[GeometryEdge]] = defaultdict(list)
        for edge in accepted:
            by_child[edge.child].append(edge)

        for child, child_edges in by_child.items():
            selected = self._select_parent_edges(child_edges)
            if not selected:
                continue
            best = selected[0]
            self.dependencies[child] = DependencyInfo(
                parent=best.parent,
                coverage=best.coverage,
                p_value=best.p_value,
                q_value=best.q_value,
                confidence=best.confidence,
                supporting_segments=best.supporting_segments,
                violating_segments=best.violating_segments,
            )

    def _collect_specifiedness_edges(self) -> tuple[GeometryEdge, ...]:
        """Collect every tested specifiedness dependency edge."""
        features = tuple(self.engine.get_contrastive_features())
        raw: list[
            tuple[
                str,
                str,
                float,
                float,
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
            ]
        ] = []

        for child_feat in features:
            spec_child = self.engine.spec_segs[child_feat]
            if len(spec_child) < self.config.min_child_support:
                continue

            for parent_feat in features:
                if child_feat == parent_feat:
                    continue

                coverage, support, violations, parent_only = (
                    self._specifiedness_counts(parent_feat, child_feat)
                )
                p_value = self._specifiedness_dependency_p_value(
                    parent_feat, child_feat
                )
                raw.append(
                    (
                        parent_feat,
                        child_feat,
                        coverage,
                        p_value,
                        support,
                        violations,
                        parent_only,
                    )
                )

        q_values: Iterable[float | None]
        if self.config.use_fdr:
            q_values = _benjamini_hochberg_q_values([item[3] for item in raw])
        else:
            q_values = (None for _ in raw)

        edges = [
            GeometryEdge(
                parent=parent_feat,
                child=child_feat,
                relation="specifiedness",
                coverage=coverage,
                p_value=p_value,
                q_value=q_value,
                confidence=self._confidence(coverage, p_value, q_value),
                supporting_segments=support,
                violating_segments=violations,
                parent_only_segments=parent_only,
            )
            for (
                parent_feat,
                child_feat,
                coverage,
                p_value,
                support,
                violations,
                parent_only,
            ), q_value in zip(raw, q_values, strict=True)
        ]
        return tuple(edges)

    def _specifiedness_counts(
        self, parent_feat: str, child_feat: str
    ) -> tuple[float, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Return coverage plus support and exception sets."""
        spec = self.engine.spec_segs
        spec_child = spec[child_feat]
        spec_parent = spec[parent_feat]

        if not spec_child:
            return 0.0, (), (), tuple(sorted(spec_parent))

        support = tuple(sorted(spec_child & spec_parent))
        violations = tuple(sorted(spec_child - spec_parent))
        parent_only = tuple(sorted(spec_parent - spec_child))
        coverage = len(support) / len(spec_child)
        return coverage, support, violations, parent_only

    def _compute_coverage(self, parent_feat: str, child_feat: str) -> float:
        """Fraction of segs where ``child`` specified implies ``parent``
        specified. Kept for compatibility with older tests.
        """
        coverage, _, _, _ = self._specifiedness_counts(parent_feat, child_feat)
        return coverage

    def _specifiedness_dependency_p_value(
        self, parent_feat: str, child_feat: str
    ) -> float:
        """Hypergeometric one-sided p-value for specifiedness overlap.

        Under the null, the count of segments where both parent and
        child are specified follows ``Hypergeometric(N, K, M)``, with
        ``N`` equal to total segments, ``K`` equal to parent-specified
        segments, and ``M`` equal to child-specified segments.
        """
        spec = self.engine.spec_segs
        n = len(self.engine.segments)
        spec_child = spec[child_feat]
        applicable = len(spec_child)
        if applicable == 0:
            return 1.0
        spec_parent = spec[parent_feat]
        parent_count = len(spec_parent)
        if parent_count == 0:
            return 1.0
        observed_holds = len(spec_child & spec_parent)
        return _hypergeom_sf(observed_holds, n, parent_count, applicable)

    def _permutation_test(
        self, parent_feat: str, child_feat: str, observed_coverage: float
    ) -> float:
        """Compatibility wrapper for older tests.

        The implementation is not a permutation test. It is the exact
        hypergeometric p-value used by
        :py:meth:`_specifiedness_dependency_p_value`.
        """
        return self._specifiedness_dependency_p_value(parent_feat, child_feat)

    def _confidence(
        self,
        coverage: float,
        p_value: float,
        q_value: float | None,
    ) -> ConfidenceLabel:
        significance = q_value if q_value is not None else p_value
        if (
            coverage >= self.config.high_coverage_threshold
            and significance < self.config.significance_level
        ):
            return "high"
        if coverage >= self.config.moderate_coverage_threshold:
            return "medium"
        return "low"

    def _accepted_edges(
        self, edges: Sequence[GeometryEdge]
    ) -> tuple[GeometryEdge, ...]:
        """Keep edges strong enough to be analysis candidates."""
        out = [
            edge
            for edge in edges
            if (
                edge.coverage >= self.config.moderate_coverage_threshold
                and (
                    (
                        edge.q_value
                        if edge.q_value is not None
                        else edge.p_value
                    )
                    < self.config.significance_level
                )
            )
        ]
        out.sort(
            key=lambda edge: (
                edge.child,
                -edge.coverage,
                edge.q_value if edge.q_value is not None else edge.p_value,
                edge.parent,
            )
        )
        return tuple(out)

    def _select_parent_edges(
        self, edges: Sequence[GeometryEdge]
    ) -> tuple[GeometryEdge, ...]:
        """Select the strongest display parents for one child."""
        ranked = sorted(
            edges,
            key=lambda edge: (
                -edge.coverage,
                edge.q_value if edge.q_value is not None else edge.p_value,
                -self._parent_specificity(edge.parent),
                edge.parent,
            ),
        )
        return tuple(ranked[: self.config.max_parents_per_child])

    def _parent_specificity(self, parent_feat: str) -> float:
        """Higher values mean the parent is specified on fewer segments."""
        total = len(self.engine.segments)
        if total == 0:
            return 0.0
        return 1.0 - (len(self.engine.spec_segs[parent_feat]) / total)

    def _build_tree(self) -> GeometryNode:
        nodes = {
            feature: GeometryNode(feature) for feature in self.engine.features
        }
        root_candidates = set(self.engine.features)

        for child_feat, dep_info in self.dependencies.items():
            parent_feat = dep_info.parent
            if self._would_create_cycle(parent_feat, child_feat):
                continue

            child_node = nodes[child_feat]
            parent_node = nodes[parent_feat]
            parent_node._add_child(child_node)
            child_node.coverage = dep_info.coverage
            child_node.p_value = dep_info.p_value
            child_node.q_value = dep_info.q_value
            child_node.confidence = dep_info.confidence
            root_candidates.discard(child_feat)

        parent_to_children: dict[str, list[str]] = defaultdict(list)
        for child_feat, dep_info in self.dependencies.items():
            child_node = nodes[child_feat]
            if child_node.parent is None:
                continue
            parent_to_children[dep_info.parent].append(child_feat)

        for children in parent_to_children.values():
            for i, child1 in enumerate(sorted(children)):
                for child2 in sorted(children)[i + 1 :]:
                    nodes[child1]._add_sibling(nodes[child2])

        return self._root_node(nodes, root_candidates)

    def _would_create_cycle(self, parent_feat: str, child_feat: str) -> bool:
        """Return True if adding parent -> child would cycle."""
        current = parent_feat
        seen: set[str] = set()
        while current in self.dependencies:
            if current == child_feat:
                return True
            if current in seen:
                return True
            seen.add(current)
            current = self.dependencies[current].parent
        return False

    def _root_node(
        self,
        nodes: Mapping[str, GeometryNode],
        root_candidates: set[str],
    ) -> GeometryNode:
        """Build a deterministic root node for the tree view."""
        if len(root_candidates) == 1:
            return nodes[next(iter(root_candidates))]

        root = GeometryNode("ROOT")
        if root_candidates:
            for feat in sorted(root_candidates):
                root._add_child(nodes[feat])
            return root

        # All nodes had inferred parents, or edges were skipped for cycle
        # safety. Attach whatever remains parentless.
        parentless = [node for node in nodes.values() if node.parent is None]
        for node in sorted(parentless, key=lambda item: item.feature):
            root._add_child(node)
        return root

    def get_dependency_summary(self) -> list[dict[str, Any]]:
        """Discovered dependencies sorted by confidence, then coverage."""
        confidence_order = {"high": 0, "medium": 1, "low": 2}
        summary = [
            {
                "child": child_feat,
                "parent": dep_info.parent,
                "coverage": dep_info.coverage,
                "p_value": dep_info.p_value,
                "q_value": dep_info.q_value,
                "confidence": dep_info.confidence,
                "supporting_segments": dep_info.supporting_segments,
                "violating_segments": dep_info.violating_segments,
            }
            for child_feat, dep_info in self.dependencies.items()
        ]
        summary.sort(
            key=lambda item: (
                confidence_order[cast(str, item["confidence"])],
                -cast(float, item["coverage"]),
                cast(str, item["child"]),
                cast(str, item["parent"]),
            )
        )
        return summary

    def get_all_edges(self) -> tuple[GeometryEdge, ...]:
        """Return every accepted inferred edge, not just tree parents."""
        return self.all_edges
