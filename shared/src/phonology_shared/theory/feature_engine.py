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

from phonology_shared.chart.consonants import group_segments
from phonology_shared.data.inventory import (
    VALID_VALUES,
    Inventory,
    normalize_feature_bundle,
)

_log = logging.getLogger(__name__)

# Singleton read-only empty mapping shared across the universal-class
# and no-spec-found return paths. Module-level so every empty result
# is the same object; callers cannot mutate it, and there is no
# per-call allocation.
_EMPTY_BUNDLE: Mapping[str, str] = MappingProxyType({})


class MatchMode(StrEnum):
    """How feature-bundle requests are evaluated against segments.

    ``STRICT`` (the historical default and the one the desktop +
    web FEAT pane currently uses): a segment matches a requested
    ``+``/``-`` only when its own feature value is that explicit
    value. ``"0"`` is its OWN value; a request of ``+`` does not
    match a segment whose feature is ``"0"``, and a request of
    ``"0"`` returns only segments whose feature is unspecified.
    This is the "round-trip" semantics
    :py:meth:`FeatureEngine.find_all_minimal_bundles` relies on:
    any bundle the engine returns, typed into the feat pane,
    yields exactly the input set.

    ``WILDCARD`` ("Allow underspecified"): a segment matches a
    requested ``+``/``-`` unless its own feature value is the
    OPPOSITE explicit value. ``"0"`` on a segment is compatible
    with either polarity. A request of ``"0"`` carries no
    constraint at all: wildcard mode reads it as "I don't care
    about this feature," not "show me unspecified segments."
    Users who want the latter stay in strict mode.

    The two modes share the same membership data
    (:py:attr:`FeatureEngine.plus_segs` / ``minus_segs`` /
    ``spec_segs``); only the lookup arithmetic differs. Wildcard
    mode is opt-in everywhere: every engine method's ``mode``
    keyword defaults to ``MatchMode.STRICT``, and the payload
    returned to renderers carries a ``matching_mode`` field so
    strict and wildcard results can never be confused at the UI
    layer.
    """

    STRICT = "strict"
    WILDCARD = "wildcard"


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
    features as bundle candidates. That restriction is what ensures
    any spec the engine LISTS round-trips exactly through
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

    * **Concept A, definition of the selected set.** Applies when
      ``S`` is already a strict natural class. Carried in
      :py:attr:`selected_minimal_bundles`: the minimal feature
      bundle(s) ``B`` such that ``find_segments(B) == S``.
    * **Concept B, completion of the selected set.** Applies when
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
    non-empty whenever the verdict is "No"; the solver never
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
        # Wildcard-only "exclusively that polarity" indices: a contour
        # segment that is BOTH + and - for a feature (its two phases
        # disagree) is excluded from neither, so wildcard subtraction
        # uses these instead of the full plus/minus sets. For a
        # single-phase inventory plus/minus are disjoint and these
        # equal the full sets, so behaviour is unchanged.
        self._plus_excl: dict[str, frozenset[str]] = {}
        self._minus_excl: dict[str, frozenset[str]] = {}
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
        # ``(frozenset(segments), match_mode)`` because the same
        # selection yields DIFFERENT minimal bundles under strict vs.
        # wildcard semantics (wildcard's candidate space is wider, so
        # its minimal bundles are typically shorter). Stored as
        # tuples of MappingProxyType so a caller cannot mutate the
        # cached result and corrupt subsequent queries on the same
        # input.
        self._bundle_cache: dict[
            tuple[frozenset[str], MatchMode],
            tuple[Mapping[str, str], ...],
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

    def _find_segments_unsorted(
        self,
        feature_spec: Mapping[str, str],
        *,
        mode: MatchMode = MatchMode.STRICT,
    ) -> list[str]:
        """Match segments against a feature spec; unsorted result.

        Both modes are membership-set intersections (vertical, not
        per-segment scans):

        STRICT: ``+`` matches only ``plus_segs[f]``, ``-`` matches
        only ``minus_segs[f]``, and a requested ``"0"`` matches
        only ``all - spec_segs[f]`` (segments with the feature
        explicitly absent or ``"0"``). This is the user-typed
        feat→seg query semantics and the round-trip rule
        :py:meth:`find_all_minimal_bundles` relies on.

        WILDCARD: ``+`` excludes only segments that are EXCLUSIVELY
        ``-`` for the feature (``_minus_excl[f]``), ``-`` excludes
        only the exclusively-``+`` ones, and a requested ``"0"`` is a
        no-op (no constraint added). A contour segment that is both
        ``+`` and ``-`` (its phases disagree) is in neither exclusive
        set, so it survives a query for EITHER polarity, which is the
        point: a diphthong gliding into ``[+low]`` must still answer a
        ``[+low]`` query. For single-phase inventories the exclusive
        sets equal the full ``minus_segs`` / ``plus_segs``, so this is
        the unchanged behaviour. ``"0"``-on-segment is compatible with
        either polarity; the only thing wildcard rules out is an
        explicit, non-contour opposite. See :py:class:`MatchMode` for
        the rationale.

        Either way, a fresh call is ``O(F)`` over the spec.
        """
        matched: frozenset[str] = self._all_segments
        if mode is MatchMode.WILDCARD:
            for feature, value in feature_spec.items():
                if value == "+":
                    matched -= self._minus_excl[feature]
                elif value == "-":
                    matched -= self._plus_excl[feature]
                # value == "0": wildcard interprets as "no
                # constraint." A user who wants the explicit-
                # underspec semantic stays in strict mode.
                if not matched:
                    break
            return list(matched)
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
        """Populate the membership sets in one pass.

        Membership UNIONS over a segment's phases (see
        :py:meth:`Inventory.segment_phases`): a contour segment is a
        member of ``[+f]`` if ANY phase is ``+f`` and of ``[-f]`` if
        ANY phase is ``-f``, so a diphthong that glides ``-low`` ->
        ``+low`` lands in both classes. A single-phase segment indexes
        exactly as before. The per-feature ``_plus_excl`` /
        ``_minus_excl`` hold the "exclusively that polarity" segments
        for the wildcard path.
        """
        features = self._inventory.features
        spec: dict[str, set[str]] = {f: set() for f in features}
        plus: dict[str, set[str]] = {f: set() for f in features}
        minus: dict[str, set[str]] = {f: set() for f in features}
        for seg in self._inventory.segments:
            for phase in self._inventory.segment_phases(seg):
                for f in features:
                    v = phase.get(f, "0")
                    if v == "+":
                        spec[f].add(seg)
                        plus[f].add(seg)
                    elif v == "-":
                        spec[f].add(seg)
                        minus[f].add(seg)
        self.spec_segs = {f: frozenset(s) for f, s in spec.items()}
        self.plus_segs = {f: frozenset(s) for f, s in plus.items()}
        self.minus_segs = {f: frozenset(s) for f, s in minus.items()}
        self._plus_excl = {
            f: self.plus_segs[f] - self.minus_segs[f] for f in features
        }
        self._minus_excl = {
            f: self.minus_segs[f] - self.plus_segs[f] for f in features
        }
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
    def active_features(self) -> tuple[str, ...]:
        """Features that are explicitly specified for at least one
        segment in the inventory. STRICT-mode filter.

        A feature qualifies when at least one segment has a value of
        ``+`` or ``-``. Features that are uniformly ``0`` (or
        unspecified) across every segment are dropped because under
        STRICT matching they can never participate in a query: a
        ``+f`` request returns the empty set if no segment is
        explicitly ``+f``. Features with all-``-`` values stay (the
        inventory does specify a value, and ``-`` queries still
        select segments).

        Under WILDCARD matching, the inverse holds: a feature with
        no explicit values is still queryable (a ``+f`` request
        matches every segment because nothing contradicts it).
        Callers that need the wildcard-aware list use
        :py:meth:`active_features_for_mode`; this property stays
        on the existing strict-only semantics so existing
        consumers (the feature pane, the analysis renderer)
        remain backward-compatible without a mode argument.

        Derived from :py:attr:`spec_segs` so the membership caches
        stay the single definition of "explicitly specified",
        matching :py:attr:`contrastive_features`.
        """
        return tuple(f for f in self._inventory.features if self.spec_segs[f])

    def active_features_for_mode(self, mode: MatchMode) -> tuple[str, ...]:
        """Active-feature list appropriate for ``mode``.

        STRICT: identical to :py:attr:`active_features`: the
        all-``0`` filter applies.

        WILDCARD: the full inventory feature roster. Wildcard
        mode lets users query features that are uniformly
        unspecified, so the feature pane must surface them.
        """
        if mode is MatchMode.WILDCARD:
            return self._inventory.features
        return self.active_features

    @cached_property
    def grouped_segments(self) -> dict[str, list[str]]:
        """Display-grouped segments (Plosives, Fricatives, ...).

        Lives on the engine so the cache is tied to engine identity.
        Callers do not have to remember to invalidate when swapping
        inventories; they swap engines instead. Passes the engine's
        cached normalized bundles so the inventory is normalized
        exactly once per engine, not once per grouping.
        """
        return group_segments(
            self._inventory.segments,
            normalized=self.normalized_segment_feats,
            contour_feats=self._contour_feats_by_seg,
        )

    @cached_property
    def _contour_feats_by_seg(self) -> dict[str, frozenset[str]]:
        """Per-segment set of (normalized) features that contour.

        For each multi-phase segment, the feature names whose value
        takes BOTH ``+`` and ``-`` across its phases. Names are folded
        with :py:func:`normalize_feature_bundle` so they share the
        grouper's namespace (lowercase short codes). Single-phase
        segments contribute nothing. The grouper reads it to classify
        a ``continuant``-contour obstruent as an affricate without a
        ``DelRel`` feature; see :py:meth:`Inventory.segment_phases`."""
        out: dict[str, frozenset[str]] = {}
        for seg in self._inventory.segments:
            phases = self._inventory.segment_phases(seg)
            if len(phases) < 2:
                continue
            norm_phases = [normalize_feature_bundle(p) for p in phases]
            keys = {k for p in norm_phases for k in p}
            contour = frozenset(
                f
                for f in keys
                if {p.get(f, "0") for p in norm_phases} >= {"+", "-"}
            )
            if contour:
                out[seg] = contour
        return out

    @cached_property
    def normalized_segment_feats(self) -> dict[str, dict[str, str]]:
        """Per-segment feature bundles with names normalized to the
        engine's canonical keys via
        :py:func:`normalize_feature_bundle`. Same lifetime and
        invalidation story as :py:attr:`grouped_segments`."""
        return {
            seg: normalize_feature_bundle(self._inventory.segments[seg])
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
        mode: MatchMode = MatchMode.STRICT,
    ) -> list[str]:
        """Sorted list of segments matching a (possibly partial) spec.

        ``mode`` selects between :py:class:`MatchMode`'s STRICT
        (default) and WILDCARD interpretations of ``+`` / ``-`` /
        ``"0"`` requests. See :py:class:`MatchMode` for the
        per-cell rules and the design rationale.

        The GUI's feat→seg query path calls this with the default
        strict mode; the wildcard ("Allow underspecified") UI
        toggle threads ``mode=MatchMode.WILDCARD`` from the bridge
        through to here.
        """
        for feature, value in feature_spec.items():
            self._validate_feature(feature)
            if value not in VALID_VALUES:
                raise ValueError(
                    f"Invalid feature value '{value}' for '{feature}'"
                )
        return sorted(self._find_segments_unsorted(feature_spec, mode=mode))

    def find_all_minimal_bundles(
        self,
        segments: list[str],
        *,
        mode: MatchMode = MatchMode.STRICT,
        max_bundles: int = 10_000,
    ) -> tuple[Mapping[str, str], ...]:
        """Every minimal feature bundle that characterises ``segments``.

        Under STRICT (default): ``find_segments(B, mode=STRICT) ==
        set(segments)``: round-trip equality. Candidates are
        features where every selected segment shares the same
        explicit ``+`` / ``-`` (a ``"0"`` cell disqualifies the
        feature).

        Under WILDCARD: ``find_segments(B, mode=WILDCARD) ==
        set(segments)``: round-trip under wildcard semantics.
        Candidates widen: a ``(f, "+")`` candidate exists whenever
        no selected segment is explicitly ``-f``; a ``(f, "-")``
        candidate exists whenever no selected segment is explicitly
        ``+f``. A feature with no explicit value in the selection
        contributes BOTH candidates (each excludes a different set
        of outside segments). Bundles emitted here are minimal
        *compatibility* specifications, not minimal strict specs;
        renderers label them as such.

        Returns up to ``max_bundles`` bundles (truncation is
        silent; compare ``len(result)`` to detect).

        Returns ``(EMPTY_BUNDLE,)`` ONLY for the universal class;
        ``()`` for non-NC sets and for ``∅``. The UI presents the
        ``()`` case as "not a natural class" and offers
        :py:meth:`complete_to_minimal_natural_class` for the
        active mode.

        Memoised on ``(frozenset(segments), mode)``: same selection
        with different modes does not collide. Truncated results
        (searches that hit ``max_bundles``) are never cached, so the
        cache stays a pure function of ``(selection, mode)``.
        """
        if not segments:
            return ()
        seg_map = self._inventory.segments
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        all_segments = self._all_segments
        for seg in segments:
            if seg not in seg_map:
                raise KeyError(f"Segment '{seg}' not in inventory")
        selected: frozenset[str] = frozenset(segments)
        cache_key = (selected, mode)
        cached = self._bundle_cache.get(cache_key)
        if cached is not None:
            return cached
        outside_set = all_segments - selected
        if not outside_set:
            self._bundle_cache[cache_key] = (_EMPTY_BUNDLE,)
            return self._bundle_cache[cache_key]

        # Candidate generation diverges by mode but the rest of the
        # hitting-set algorithm is identical.
        # ``candidate_pairs`` is the list of (feature, value)
        # constraints the search may choose from. ``excludes_by``
        # maps a candidate ID to the set of outside segments that
        # constraint rules out.
        if mode is MatchMode.WILDCARD:
            candidate_pairs = self._wildcard_candidate_constraints(selected)
            # Wildcard constraint excludes the OPPOSITE-explicit
            # segments: (f, "+") rules out only minus_segs[f];
            # (f, "-") rules out only plus_segs[f]. ``"0"``
            # outside segments are NOT excluded by any constraint
            #: wildcard tolerates them everywhere.
            excludes_lookup: list[frozenset[str]] = [
                (
                    (minus_segs[f] & outside_set)
                    if v == "+"
                    else (plus_segs[f] & outside_set)
                )
                for f, v in candidate_pairs
            ]
        else:
            strict_candidates = self._strict_candidate_constraints(selected)
            candidate_pairs = list(strict_candidates.items())
            # Strict excluder collection: outside t is excluded by
            # (f, +) iff t is not explicitly + on f.
            excludes_lookup = [
                (outside_set - (plus_segs[f] if v == "+" else minus_segs[f]))
                for f, v in candidate_pairs
            ]
        if not candidate_pairs:
            # No constraint can be applied; only the universal class
            # contains the selection, and the universal class is
            # ``S`` only when outside is empty (handled above). So
            # this branch means "not a natural class under ``mode``".
            self._bundle_cache[cache_key] = ()
            return self._bundle_cache[cache_key]

        # Preserve the historical iteration order of ``outside`` so
        # the heavy-hitter sort below is deterministic.
        outside = [s for s in seg_map if s in outside_set]

        # Hitting-set search via bitmask. Each candidate pair gets a
        # bit index 0..N-1; the chosen set, the still-available set,
        # and each excluder become single Python ints. Pairs are
        # ordered by how often they appear in excluders so
        # branch-and-bound prunes earlier.
        n_candidates = len(candidate_pairs)
        counts = [0] * n_candidates
        raw_excluders: list[list[int]] = []
        for seg in outside:
            exc_idxs = [
                i
                for i, excluded in enumerate(excludes_lookup)
                if seg in excluded
            ]
            if not exc_idxs:
                # This outside segment is excluded by NO candidate
                # under the current mode: selection cannot be a
                # natural class.
                self._bundle_cache[cache_key] = ()
                return self._bundle_cache[cache_key]
            raw_excluders.append(exc_idxs)
            for i in exc_idxs:
                counts[i] += 1
        order = sorted(
            range(n_candidates), key=lambda i: counts[i], reverse=True
        )
        # Map original-index -> new-bit-index so excluder masks can
        # be built in the heavy-hitter ordering.
        old_to_bit = [0] * n_candidates
        for new_idx, old_idx in enumerate(order):
            old_to_bit[old_idx] = 1 << new_idx
        # Many outside segments share an exclusion pattern (identical
        # candidate sets rule them out), and duplicate masks impose
        # the same coverage constraint. Deduplicate once so the
        # search scans each distinct constraint exactly once.
        excluder_bits = sorted(
            {
                sum(old_to_bit[i] for i in exc_idxs)
                for exc_idxs in raw_excluders
            }
        )
        ordered_pairs = [candidate_pairs[i] for i in order]
        n = n_candidates
        all_remaining = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            all_remaining[i] = all_remaining[i + 1] | (1 << i)

        results: list[dict[str, str]] = []
        best_size: int | None = None

        def _bits_to_bundle(bits: int) -> dict[str, str]:
            return {
                ordered_pairs[i][0]: ordered_pairs[i][1]
                for i in range(n)
                if bits & (1 << i)
            }

        # ``uncovered`` threads the still-unsatisfied excluder masks
        # down the recursion: choosing a candidate filters out every
        # mask it covers, so the satisfaction check is "is the list
        # empty" and the feasibility prunes scan only constraints
        # that can still fail. The previous shape rescanned the full
        # excluder list three times per node, which made wildcard
        # single-segment clicks cost seconds on dense inventories.
        def backtrack(
            idx: int, depth: int, chosen_bits: int, uncovered: list[int]
        ) -> bool:
            nonlocal best_size
            if not uncovered:
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
            # ``uncovered`` masks are disjoint from ``chosen_bits``
            # by construction, so feasibility only needs the
            # remaining candidate bits.
            remaining_bits = all_remaining[idx]
            for eb in uncovered:
                if not (eb & remaining_bits):
                    return True
            bit = 1 << idx
            still = [eb for eb in uncovered if not (eb & bit)]
            if not backtrack(idx + 1, depth + 1, chosen_bits | bit, still):
                return False
            remaining_without = all_remaining[idx + 1]
            for eb in uncovered:
                if not (eb & remaining_without):
                    return True
            return backtrack(idx + 1, depth, chosen_bits, uncovered)

        backtrack(0, 0, 0, excluder_bits)
        frozen = tuple(MappingProxyType(b) for b in results)
        # Only memoize complete searches. A capped search returns a
        # truncated tuple; caching it would poison later calls made
        # with a higher (or default) ``max_bundles``.
        if len(results) < max_bundles:
            self._bundle_cache[cache_key] = frozen
        return frozen

    def compute_natural_class(
        self,
        segments: list[str],
        *,
        mode: MatchMode = MatchMode.STRICT,
    ) -> Mapping[str, str] | None:
        """One minimal feature bundle characterising the segment set.

        Three distinct return shapes:

        * a non-empty mapping: the minimal feature bundle.
        * an empty mapping: the segments form the universal class
          (every segment in the inventory).
        * ``None``: the segments are not a natural class under
          ``mode``.

        The mapping (when not ``None``) is read-only, a view into
        the per-engine bundle cache.
        """
        bundles = self.find_all_minimal_bundles(segments, mode=mode)
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

        Hot path: called once per selection change. No memoization
        because the worst case is well under the per-click repaint
        budget; re-run :py:mod:`shared.tests.bench.bench_feature_categories`
        before adding a cache.
        """
        if not segments:
            return {}
        # Validate like every other segment-accepting entry point.
        # A stale selection surviving an inventory switch must raise,
        # not silently skew ``n`` and classify everything as
        # ALL_ZERO / UNDERSPEC_*.
        for seg in segments:
            if seg not in self._all_segments:
                raise KeyError(f"Segment '{seg}' not in inventory")
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

        Identical to the strict natural-class candidate rule: a
        feature is "shared" iff every selected segment has the same
        explicit value on it. Delegates to
        :py:meth:`_strict_candidate_constraints` so the strict-NC
        contract has one source of truth across this method,
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

    def _wildcard_candidate_constraints(
        self, selected: frozenset[str]
    ) -> list[tuple[str, str]]:
        """Wildcard candidate constraints of ``selected``.

        A (feature, value) pair is a wildcard candidate iff no
        selected segment carries the OPPOSITE explicit value:

        - ``(f, '+')`` is a candidate iff
          ``selected & minus_segs[f] == ∅``: i.e. no member of
          the selection is explicitly ``-f``.
        - ``(f, '-')`` is a candidate iff
          ``selected & plus_segs[f] == ∅``: i.e. no member is
          explicitly ``+f``.

        A feature with no explicit value in the selection (every
        member is ``'0'``/absent) yields BOTH candidates because
        neither contradicts. Strict mode silently disqualifies
        that feature; wildcard keeps both options on the table for
        the hitting-set search.

        Returns a list of ``(feature, value)`` pairs preserving
        feature-declaration order. List rather than dict because a
        single feature can produce two candidate entries.
        """
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        candidates: list[tuple[str, str]] = []
        for feature in self._inventory.features:
            if not (selected & minus_segs[feature]):
                candidates.append((feature, "+"))
            if not (selected & plus_segs[feature]):
                candidates.append((feature, "-"))
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
        self,
        segments: list[str],
        *,
        mode: MatchMode = MatchMode.STRICT,
    ) -> NaturalClassCompletion:
        """The smallest natural class containing ``segments`` under
        ``mode``.

        Returns a :py:class:`NaturalClassCompletion`:

        * ``already_natural_class`` → ``selected_minimal_bundles``
          carries the minimal bundles of ``S`` under ``mode``.
        * ``one_minimal_completion`` → ``additions[0]`` carries
          the segments needed to complete ``S`` into a natural
          class under ``mode``. ``selected_minimal_bundles`` is
          empty (callers needing the minimal specs of the
          completed class re-call :py:meth:`find_all_minimal_bundles`
          on ``S ∪ additions[0]``).

        **Algorithm.** Intersect the extents of every candidate
        constraint that doesn't exclude any member of ``S``:

        - STRICT: ``∩{plus_segs[f] | S ⊆ plus_segs[f]} ∩
          {minus_segs[f] | S ⊆ minus_segs[f]}``.
        - WILDCARD: ``∩{all - minus_segs[f] | S ∩ minus_segs[f] = ∅}
          ∩ {all - plus_segs[f] | S ∩ plus_segs[f] = ∅}``.

        ``additions = smallest_class - S``. Guaranteed exact (no
        search budget, no fallback) under either mode. The
        wildcard completion is always a subset of the strict
        completion because wildcard's candidate set is wider.
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
        own_bundles = self.find_all_minimal_bundles(segments, mode=mode)
        if own_bundles:
            return NaturalClassCompletion(
                status="already_natural_class",
                selected_minimal_bundles=own_bundles,
                additions=(),
            )
        selected = frozenset(segments)
        plus_segs = self.plus_segs
        minus_segs = self.minus_segs
        smallest_class: frozenset[str] = self._all_segments
        if mode is MatchMode.WILDCARD:
            # Wildcard (f, +) candidate exists iff no member of S is
            # explicitly -f; its extent rules out only the explicit
            # -f segments. Same shape for the (-) side.
            for feat in self._inventory.features:
                if not (selected & minus_segs[feat]):
                    smallest_class -= minus_segs[feat]
                if not (selected & plus_segs[feat]):
                    smallest_class -= plus_segs[feat]
        else:
            for feat, val in self._strict_candidate_constraints(
                selected
            ).items():
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
        self,
        segments: list[str],
        *,
        mode: MatchMode = MatchMode.STRICT,
    ) -> tuple[bool, tuple[Mapping[str, str], ...]]:
        """Return ``(is_natural_class, minimal_bundles)``.

        STRICT (default): a set is a natural class iff some bundle
        ``B`` satisfies ``find_segments(B, mode=STRICT) == segments``
        under strict equality (``'0' != '+' != '-'``). This is the
        user-typed feat→seg semantics; round-trip exact.

        WILDCARD: same definition with wildcard matching. More
        permissive: many selections that fail under strict
        succeed under wildcard (with shorter, "minimal compatible"
        bundles).

        Returns ``(False, ())`` when no bundle exists under the
        active mode. The UI offers
        :py:meth:`complete_to_minimal_natural_class` for the same
        mode.

        The bundle tuple is a read-only view into the per-engine
        cache; callers may iterate but must not mutate.
        """
        bundles = self.find_all_minimal_bundles(segments, mode=mode)
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
        """``n`` closest segments to ``segment`` by feature distance.

        Equivalent to mapping :py:meth:`segment_distance` across the
        inventory but skips the per-pair validation and dictionary
        re-lookup. For inventories on the order of the Hayes count,
        the inner Python overhead dominated.
        """
        self._validate_segment(segment)
        target = self._seg_value_tuples[segment]
        tuples = self._seg_value_tuples
        distances: list[tuple[str, int]] = []
        for other, values in tuples.items():
            if other == segment:
                continue
            distances.append(
                (
                    other,
                    sum(
                        1
                        for a, b in zip(target, values, strict=True)
                        if a != b
                    ),
                )
            )
        distances.sort(key=lambda x: (x[1], x[0]))
        return distances[:n]

    def get_inventory_stats(self) -> dict[str, int | float | str]:
        """Summary stats: name, segment/feature counts, contrastive
        count, average distance.

        ``avg_feature_distance`` is ``O(n^2 * |features|)`` over the
        inventory and is recomputed on every call. Callers that hit
        this on a hot path should cache the result themselves.
        """
        # ``or "Unknown"`` (not a ``.get`` default) so a present-but-
        # empty or ``None`` name still reads "Unknown" rather than
        # stringifying to "" or "None" in the stats line.
        name = self.metadata.get("name") or "Unknown"
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
