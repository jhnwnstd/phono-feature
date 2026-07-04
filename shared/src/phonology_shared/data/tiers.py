"""Per-feature tier representation of a segment: the faithful ground
layer beneath the engine's phase and query machinery.

A segment is a set of per-feature value SEQUENCES (tiers), stored
verbatim from the source. A feature that does not change over the
segment is a length-1 tier; a feature that contours lists the values it
traverses, in order (PHOIBLE writes ``continuant`` on an affricate as
``"-,+"``). This is the source-agnostic ground truth. Following Bale &
Reiss (2018), a matrix is a PARTIAL function from attributes to values,
so a phase need not value every attribute; the ``"0"`` state is genuine
(present-and-``0`` is an asserted not-applicable) and distinct from a
feature being ABSENT from the map (source silence).

Two views are DERIVED from the tiers and never stored:

* :func:`onset` / :func:`offset` read index ``0`` / ``-1`` of every
  tier. Because every tier spans the whole segment, these anchors are
  TOTAL bundles for any segment, ragged interior or not.
* :func:`align` reconstructs an ordered sequence of :class:`Phase` s,
  but ONLY when the varying tiers agree on length. When they disagree
  (features on independent autosegmental tiers, Goldsmith 1976) it
  returns :class:`Misaligned`; a multi-feature co-occurrence query over
  such a segment is :data:`UNDETERMINED`, never guessed.

Contour is a derived set predicate over a single tier (:func:`contour_on`),
computed at query time, never stored as a value. Single-feature reads
(:func:`feature_reaches`, :func:`feature_throughout`, :func:`contour_on`)
answer for EVERY segment, ragged or not, because one tier never needs an
alignment; only multi-feature co-occurrence does.

The module knows nothing about any particular source's alphabet: it
works in the canonical three-value vocabulary ``"+"`` / ``"-"`` / ``"0"``,
and a source adapter is responsible for folding raw cells onto it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable, Mapping, Union

#: Canonical feature values. A source adapter maps its own tokens onto
#: these before anything here runs.
PLUS: Final = "+"
MINUS: Final = "-"
NIL: Final = "0"

#: One feature's ordered value sequence (its tier).
Tier = tuple[str, ...]
#: A segment's ground representation: feature -> tier. A feature ABSENT
#: from this map is source silence (unknown), which
#: :func:`feature_reaches` treats as "does not reach" and
#: :func:`onset` / :func:`offset` simply omit.
TierMap = Mapping[str, Tier]


class Attrs:
    """Assigns each attribute a bit index so a :class:`Phase`'s ``+`` and
    ``-`` states are two disjoint bitmasks and subset / contour tests are
    single word operations. Built once per feature roster."""

    __slots__ = ("_ix",)

    def __init__(self, names: Iterable[str]) -> None:
        self._ix = {name: i for i, name in enumerate(names)}

    def bit(self, name: str) -> int:
        return 1 << self._ix[name]

    def __contains__(self, name: str) -> bool:
        return name in self._ix

    def __len__(self) -> int:
        return len(self._ix)


@dataclass(frozen=True, slots=True)
class Phase:
    """A partial function ``attr -> {+,-}`` as two disjoint bitmasks.

    A bit set in :attr:`pos` means the attribute is ``+`` in this phase,
    a bit in :attr:`neg` means ``-``, and a bit in NEITHER is the ``"0"``
    state (asserted not-applicable / unspecified). Totality is NOT
    required, only disjointness: a phase is a function, so it never maps
    one attribute to both polarities. That disjointness is the invariant
    the whole set theory rests on; the ``±`` value fails precisely
    because it would break it.
    """

    pos: int
    neg: int

    def disjoint(self) -> bool:
        return (self.pos & self.neg) == 0

    def satisfies(self, want_pos: int, want_neg: int) -> bool:
        """STRICT subset test: every ``+`` and ``-`` the query asks for is
        present in this phase. A ``"0"`` attribute in the phase satisfies
        NEITHER polarity, so ``"0"`` is its own value, exactly as the
        engine's strict mode requires."""
        return (self.pos & want_pos) == want_pos and (
            self.neg & want_neg
        ) == want_neg


@dataclass(frozen=True, slots=True)
class Aligned:
    """A segment whose varying tiers share one length, so it projects to
    an ordered sequence of phases the whole engine can read."""

    phases: tuple[Phase, ...]


@dataclass(frozen=True, slots=True)
class Misaligned:
    """A segment whose varying tiers disagree on length: the source
    states each feature's change sequence but no association across them
    (separate autosegmental tiers). The endpoints (:func:`onset` /
    :func:`offset`) are still total, but multi-feature co-occurrence in a
    single interior phase is not derivable, so it is
    :data:`UNDETERMINED`."""

    lengths: tuple[int, ...]
    features: tuple[str, ...]


Alignment = Union[Aligned, Misaligned]


class _Undetermined:
    """Sentinel for a query the source underdetermines (a multi-feature
    co-occurrence over a :class:`Misaligned` segment). Distinct from
    ``True`` / ``False``: the source states neither."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "UNDETERMINED"

    def __bool__(self) -> bool:
        raise TypeError(
            "UNDETERMINED is not truthy or falsy; a caller must decide "
            "how the source's silence composes (strict excludes, "
            "wildcard includes)."
        )


#: The third query outcome, returned only for a multi-feature bundle over
#: a :class:`Misaligned` segment. Callers map it onto their mode: strict
#: matching excludes it (cannot confirm), wildcard includes it (cannot
#: refute), mirroring how an unspecified ``"0"`` already behaves.
UNDETERMINED: Final = _Undetermined()


# --------------------------------------------------------------------
# Single-feature reads: answer for EVERY segment, ragged or not, because
# one tier never needs an alignment.
# --------------------------------------------------------------------


def contour_on(tiers: TierMap, feature: str) -> bool:
    """True when ``feature`` traverses both ``+`` and ``-`` within the
    segment. The derived contour predicate; never a stored value."""
    tier = tiers.get(feature, ())
    return PLUS in tier and MINUS in tier


def feature_reaches(tiers: TierMap, feature: str, want: str) -> bool:
    """``∃``: some phase values ``feature`` as ``want``. A feature absent
    from the map is source silence and reaches nothing."""
    return want in tiers.get(feature, ())


def feature_throughout(tiers: TierMap, feature: str, want: str) -> bool:
    """``∀``: every phase values ``feature`` as ``want`` (and the feature
    is present at all)."""
    tier = tiers.get(feature, ())
    return len(tier) > 0 and all(value == want for value in tier)


# --------------------------------------------------------------------
# Derived views over the whole segment.
# --------------------------------------------------------------------


def onset(tiers: TierMap) -> dict[str, str]:
    """The segment's start anchor: index ``0`` of every tier. Total for
    any segment, since every tier spans the segment."""
    return {feature: tier[0] for feature, tier in tiers.items() if tier}


def offset(tiers: TierMap) -> dict[str, str]:
    """The segment's end anchor: index ``-1`` of every tier."""
    return {feature: tier[-1] for feature, tier in tiers.items() if tier}


def phase_of(attrs: Attrs, bundle: Mapping[str, str]) -> Phase:
    """Build a :class:`Phase` from a single-value-per-feature bundle (an
    onset/offset anchor, or one aligned column). Features not in
    ``attrs`` and ``"0"`` values contribute no bit."""
    pos = neg = 0
    for feature, value in bundle.items():
        if feature not in attrs:
            continue
        bit = attrs.bit(feature)
        if value == PLUS:
            pos |= bit
        elif value == MINUS:
            neg |= bit
    return Phase(pos, neg)


def align(attrs: Attrs, tiers: TierMap) -> Alignment:
    """Reconstruct ordered phases when the varying tiers agree on length,
    else report :class:`Misaligned`.

    A single-value tier is a constant and broadcasts across the shared
    length (licensed by the source convention that one value means "does
    not change"). Two varying tiers of different lengths express separate
    autosegmental tiers with no stated association, so alignment refuses
    rather than inventing one.
    """
    varying = {f: t for f, t in tiers.items() if len(t) > 1}
    lengths = {len(t) for t in varying.values()}
    if len(lengths) > 1:
        return Misaligned(tuple(sorted(lengths)), tuple(sorted(varying)))
    n = lengths.pop() if lengths else 1
    phases: list[Phase] = []
    for i in range(n):
        pos = neg = 0
        for feature, tier in tiers.items():
            if feature not in attrs:
                continue
            value = tier[i] if len(tier) == n else tier[0]
            bit = attrs.bit(feature)
            if value == PLUS:
                pos |= bit
            elif value == MINUS:
                neg |= bit
        phases.append(Phase(pos, neg))
    return Aligned(tuple(phases))


# --------------------------------------------------------------------
# Multi-feature bundle membership: needs co-occurrence within one phase,
# so it reads the alignment and is UNDETERMINED where it is Misaligned.
# --------------------------------------------------------------------


def bundle_bits(attrs: Attrs, spec: Mapping[str, str]) -> tuple[int, int]:
    """Compile a query ``{feature: "+"/"-"}`` into ``(want_pos,
    want_neg)`` bitmasks for :meth:`Phase.satisfies`."""
    want_pos = want_neg = 0
    for feature, value in spec.items():
        if feature not in attrs:
            continue
        bit = attrs.bit(feature)
        if value == PLUS:
            want_pos |= bit
        elif value == MINUS:
            want_neg |= bit
    return want_pos, want_neg


def member_exists(
    attrs: Attrs, alignment: Alignment, spec: Mapping[str, str]
) -> Union[bool, _Undetermined]:
    """``∃`` co-occurrence: some phase satisfies the whole bundle.
    :data:`UNDETERMINED` when the segment is :class:`Misaligned` (the
    source does not state whether the features share a phase)."""
    if isinstance(alignment, Misaligned):
        return UNDETERMINED
    want = bundle_bits(attrs, spec)
    return any(phase.satisfies(*want) for phase in alignment.phases)


def member_forall(
    attrs: Attrs, alignment: Alignment, spec: Mapping[str, str]
) -> Union[bool, _Undetermined]:
    """``∀`` co-occurrence: every phase satisfies the whole bundle.
    :data:`UNDETERMINED` for a :class:`Misaligned` segment."""
    if isinstance(alignment, Misaligned):
        return UNDETERMINED
    want = bundle_bits(attrs, spec)
    return all(phase.satisfies(*want) for phase in alignment.phases)
