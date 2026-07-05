"""Per-feature tier representation of a segment. This is the faithful
ground layer beneath the engine's phase and query machinery.

A segment is a set of per-feature value SEQUENCES (tiers), stored
verbatim from the source. A feature that does not change over the
segment is a length-1 tier. A feature that contours lists the values it
traverses, in order (PHOIBLE writes ``continuant`` on an affricate as
``"-,+"``). This is the source-agnostic ground truth. Following Bale and
Reiss (2018), a matrix is a PARTIAL function from attributes to values,
so a phase need not value every attribute. The ``"0"`` state is genuine,
since present-and-``0`` is an asserted not-applicable, and it stays
distinct from a feature being ABSENT from the map (source silence).

Two views are DERIVED from the tiers and never stored.

* :func:`onset` / :func:`offset` read index ``0`` / ``-1`` of every
  tier. Every tier spans the whole segment, so these anchors are TOTAL
  bundles for any segment, ragged interior or not.
* :func:`align` reconstructs an ordered sequence of :class:`Phase` s,
  but ONLY when the varying sequences agree on length. When they
  disagree, the source has stated each feature's own sequence and NO
  association across them, so :func:`align` returns :class:`Misaligned`
  and a multi-feature co-occurrence query over such a segment is
  :data:`UNDETERMINED`, never guessed.

Contour is a derived set predicate over a single sequence
(:func:`contour_on`), computed at query time, never stored as a value.
Single-feature reads (:func:`feature_reaches`, :func:`feature_throughout`,
:func:`contour_on`) answer for EVERY segment, ragged or not, because one
sequence never needs an alignment. Only multi-feature co-occurrence does.

The module knows nothing about any particular source's alphabet. It
works in the canonical three-value vocabulary ``"+"`` / ``"-"`` / ``"0"``,
and a source adapter folds raw cells onto it.

Pedigree, because the informal name "tier" is misleading. These are NOT
autosegmental tiers. An autosegmental tier (Goldsmith 1976; Sagey 1986)
is a SUBSTANTIVE primitive carrying association lines, dominance nodes,
and constraints like no-line-crossing, the phonetic-autonomy commitments
a substance-free program denies. What is stored here is barer. It is a
plain per-feature value SEQUENCE, a set-theoretic object with no
association lines, no geometry, and no claim about which features pattern
together (Bale and Reiss 2018; Bale, Reiss and Shen 2016). Each feature
runs as its own independent sequence and nothing asserts a cross-feature
timeline unless the data supplies one, which makes this MORE
substance-free than autosegmental tiers, not less. The four states a
feature can take, ``+``, ``-``, an asserted ``0``, and absence, are the
equipollent scheme with a silent state read faithfully off the survey
(Reiss 2017). A feature valued as a sequence is the intrasegmental-change
case (Reiss 2021). Any harmony or spreading a future grammar layer needs
is a feature-restricted SEARCH over these sets, not a reified moving tier
(Bale, Papillon and Reiss 2014).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

#: Canonical feature values. A source adapter maps its own tokens onto
#: these before anything here runs.
PLUS: Final = "+"
MINUS: Final = "-"
NIL: Final = "0"

#: One feature's ordered value sequence (its tier).
Tier = tuple[str, ...]
#: A segment's ground representation, mapping feature to tier. A feature
#: ABSENT from this map is source silence (unknown), which
#: :func:`feature_reaches` treats as "does not reach" and :func:`onset`
#: / :func:`offset` simply omit.
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
    required, only disjointness. A phase is a function, so it never maps
    one attribute to both polarities. That disjointness is the invariant
    the whole set theory rests on, and the ``±`` value fails precisely
    because it would break it.
    """

    pos: int
    neg: int

    def disjoint(self) -> bool:
        return (self.pos & self.neg) == 0

    def satisfies(self, want_pos: int, want_neg: int) -> bool:
        """STRICT subset test. Every ``+`` and ``-`` the query asks for is
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
    """A segment whose varying sequences disagree on length. The source
    states each feature's own value sequence and no association across
    them. The endpoints (:func:`onset` / :func:`offset`) are still total,
    but multi-feature co-occurrence in a single interior phase is not
    derivable, so it is :data:`UNDETERMINED`."""

    lengths: tuple[int, ...]
    features: tuple[str, ...]


Alignment = Aligned | Misaligned


class _Undetermined:
    """Sentinel for a query the source underdetermines (a multi-feature
    co-occurrence over a :class:`Misaligned` segment). Distinct from
    ``True`` / ``False``, since the source states neither."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover (debug aid)
        return "UNDETERMINED"

    def __bool__(self) -> bool:
        raise TypeError(
            "UNDETERMINED is not truthy or falsy; a caller must decide "
            "how the source's silence composes (strict excludes, "
            "wildcard includes)."
        )


#: The third query outcome, returned only for a multi-feature bundle over
#: a :class:`Misaligned` segment. Callers map it onto their mode. Strict
#: matching excludes it (cannot confirm) and wildcard includes it (cannot
#: refute), mirroring how an unspecified ``"0"`` already behaves.
UNDETERMINED: Final = _Undetermined()


# --------------------------------------------------------------------
# Single-feature reads answer for EVERY segment, ragged or not, because
# one tier never needs an alignment.
# --------------------------------------------------------------------


def contour_on(tiers: TierMap, feature: str) -> bool:
    """True when ``feature`` traverses both ``+`` and ``-`` within the
    segment. The derived contour predicate, never a stored value."""
    tier = tiers.get(feature, ())
    return PLUS in tier and MINUS in tier


def feature_reaches(tiers: TierMap, feature: str, want: str) -> bool:
    """``∃`` existential. Some phase values ``feature`` as ``want``. A
    feature absent from the map is source silence and reaches nothing."""
    return want in tiers.get(feature, ())


def feature_throughout(tiers: TierMap, feature: str, want: str) -> bool:
    """``∀`` universal. Every phase values ``feature`` as ``want``, and
    the feature is present at all."""
    tier = tiers.get(feature, ())
    return len(tier) > 0 and all(value == want for value in tier)


# --------------------------------------------------------------------
# Derived views over the whole segment.
# --------------------------------------------------------------------


def onset(tiers: TierMap) -> dict[str, str]:
    """The segment's start anchor, index ``0`` of every tier. Total for
    any segment, since every tier spans the segment."""
    return {feature: tier[0] for feature, tier in tiers.items() if tier}


def offset(tiers: TierMap) -> dict[str, str]:
    """The segment's end anchor, index ``-1`` of every tier."""
    return {feature: tier[-1] for feature, tier in tiers.items() if tier}


def phase_of(attrs: Attrs, bundle: Mapping[str, str]) -> Phase:
    """Build a :class:`Phase` from a single-value-per-feature bundle,
    either an onset or offset anchor or one aligned column. A ``"0"``
    value contributes no bit. A feature absent from ``attrs`` also
    contributes no bit, because it names no attribute in this roster and
    so has no slot to occupy. Dropping it refuses to invent an attribute
    the roster never declared, the same declared-roster-as-query-surface
    rule the membership caches follow, so the drop stays faithful rather
    than losing a value the roster could hold.
    """
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
    not change"). Two varying tiers of different lengths express
    independent value sequences with no stated association, so alignment
    refuses rather than inventing one. Each column routes through
    :func:`phase_of`, so one function packs bits and an aligned phase can
    never disagree with an onset or offset phase.
    """
    varying = {f: t for f, t in tiers.items() if len(t) > 1}
    lengths = {len(t) for t in varying.values()}
    if len(lengths) > 1:
        return Misaligned(tuple(sorted(lengths)), tuple(sorted(varying)))
    n = lengths.pop() if lengths else 1
    columns = (
        {f: (t[i] if len(t) == n else t[0]) for f, t in tiers.items()}
        for i in range(n)
    )
    return Aligned(tuple(phase_of(attrs, col) for col in columns))


# --------------------------------------------------------------------
# Multi-feature bundle membership needs co-occurrence within one phase,
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
    attrs: Attrs,
    tiers: TierMap,
    alignment: Alignment,
    spec: Mapping[str, str],
) -> bool | _Undetermined:
    """``∃`` co-occurrence. Some phase satisfies the WHOLE bundle.

    ``∃`` does NOT decompose over features, since a phase with ``f`` and
    one with ``g`` is not a phase with both, so a multi-feature bundle
    needs the phases. A requested feature the segment never reaches rules
    it out DEFINITIVELY, even when ragged, and that single-feature check
    (:func:`feature_reaches`) needs no alignment. Only when every feature
    is individually reached AND the segment is :class:`Misaligned` is the
    co-occurrence :data:`UNDETERMINED`, since the source states no shared
    phase. A single-feature bundle is decided by the reach check alone.
    """
    if not all(feature_reaches(tiers, f, w) for f, w in spec.items()):
        return False
    if len(spec) <= 1:
        return True
    if isinstance(alignment, Misaligned):
        return UNDETERMINED
    want = bundle_bits(attrs, spec)
    return any(phase.satisfies(*want) for phase in alignment.phases)


def member_forall(tiers: TierMap, spec: Mapping[str, str]) -> bool:
    """``∀`` co-occurrence. Every phase satisfies the whole bundle.

    This DECOMPOSES over features, since every phase has ``f`` AND ``g``
    iff ``f`` is its wanted value throughout AND ``g`` is throughout. So
    it reads the sequences directly (:func:`feature_throughout`), needs
    no alignment, and is ALWAYS decidable, never :data:`UNDETERMINED`,
    even for a ragged segment. The engine's query surfaces stay total the
    same way, by decomposing per feature, though they read their own
    membership caches rather than calling this helper. This is the formal
    statement those caches implement.
    """
    return all(
        feature_throughout(tiers, feature, want)
        for feature, want in spec.items()
    )
