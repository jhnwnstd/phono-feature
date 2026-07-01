"""Single source of truth for feature-name metadata.

Three concerns previously kept their own parallel tables: display
ordering (``FEATURE_ORDER``), display grouping (``FEATURE_GROUPS``),
and suprasegmental classification (``SUPRASEGMENTAL_FEATURES``), all
in :py:mod:`phonology_shared.presentation.constants`. Plus two
import-time mapping tables (``PHOIBLE_TO_APP_FEATURE``,
``PANPHON_TO_APP_FEATURE``) and a small inline alias table inside
:py:func:`phonology_shared.data.inventory.normalize_feature_key`.

Each of those was keyed on a feature SURFACE NAME (``"LABIAL"`` vs
``"Labial"``), forcing every case-variant concept to be enumerated
repeatedly with no single place answering "are ``LABIAL`` and
``Labial`` the same feature?" from the renderer.

This module replaces them with one :py:class:`FeatureMetadata`
registry keyed by the CANONICAL lowercase name. Each entry carries
every surface form (``aliases``) that maps to that concept, so the
resolver collapses ``LABIAL``, ``Labial``, ``lab``, ``LAB`` to
``labial`` in one lookup.

Display-side consumers (sort, group, suprasegmental check) call the
resolver helpers below. The surface form rendered on the panel row
stays whatever the inventory carried on disk, per the user's
contract: Hayes' shouty ``LABIAL`` stays shouty, PHOIBLE's
``Labial`` stays title-case, the backend treats them as one concept.

Place subfeatures sort adjacent to their anchor via the ``subgroup``
+ ``sort_key`` design: ``round.sort_key`` is one more than
``labial.sort_key``, so the renderer's natural sort lands modifiers
right after the anchor with no visual-hierarchy work.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache

# ---------------------------------------------------------------------
# System tags
# ---------------------------------------------------------------------

#: Tags identifying which provider's feature roster includes a given
#: feature. Used by :py:meth:`FeatureMetadata.systems`.
SYSTEM_HAYES = "hayes"
SYSTEM_PHOIBLE = "phoible"
SYSTEM_PANPHON = "panphon"

#: Tags identifying which display / classification subsystem reads
#: a given feature. Used by :py:meth:`FeatureMetadata.uses`.
USE_CONSONANT = "consonant"  # consonants.py classifier
USE_VOWEL = "vowel"  # vowels.py inference
USE_LARYNGEAL = "laryngeal"  # laryngeal display path
USE_NATURAL_CLASS = "natural_class"  # natural-class queries
USE_VOWEL_PAIR = "vowel_pair"  # in-cell contrast (long, nasal, etc.)


# ---------------------------------------------------------------------
# Group identifiers (parallel to FEATURE_GROUPS' titles)
# ---------------------------------------------------------------------

GROUP_MAJOR_CLASS = "Major Class"
GROUP_LARYNGEAL = "Laryngeal"
GROUP_MANNER = "Manner"
GROUP_PLACE = "Place"
GROUP_TONGUE_ROOT = "Tongue-Root / Pharyngeal"
GROUP_PROSODIC = "Prosodic"

#: Display order of groups in the Feature Pane. The legacy tables
#: rendered groups in this same order; preserved here so derived
#: ``FEATURE_GROUPS`` is byte-identical to the prior structure.
GROUP_ORDER: tuple[str, ...] = (
    GROUP_MAJOR_CLASS,
    GROUP_LARYNGEAL,
    GROUP_MANNER,
    GROUP_PLACE,
    GROUP_TONGUE_ROOT,
    GROUP_PROSODIC,
)


@dataclass(frozen=True, slots=True)
class FeatureMetadata:
    """One row in :py:data:`FEATURE_REGISTRY`.

    ``canonical`` is the lowercase, delimiter-stripped key that
    :py:func:`phonology_shared.data.inventory.normalize_feature_key`
    produces for every alias in ``aliases``. The registry is keyed on
    ``canonical``; ``aliases`` enumerates every surface form the
    codebase has ever seen for this concept (Hayes' all-caps anchor,
    PHOIBLE's title-case, PanPhon's short code, common typos).

    ``sort_key`` is a small integer, smaller sorting earlier. Place
    modifiers (``round``, ``anterior``, ``high``) carry sort_keys
    directly after their anchor so they cluster in the rendered list.

    ``group`` matches one of :py:data:`GROUP_ORDER`'s titles; the
    derived ``FEATURE_GROUPS`` in
    :py:mod:`phonology_shared.presentation.constants` collects every
    alias of every entry tagged with each group.

    ``subgroup`` optionally points at another entry's canonical key
    that serves as this feature's "anchor", the head of an
    articulatory subcluster the modifier refines (``"labial"`` for
    ``round`` / ``labiodental``, ``"voice"`` for ``fortis`` /
    ``lenis`` / ``breathy`` / ``creaky``, ``"constrgl"`` for
    ``raisedlarynxejective`` / ``loweredlarynximplosive``). Used only
    by tests and inspection; rendering is sort-adjacency, no visual
    hierarchy. The ``test_modifiers_sort_directly_after_their_anchor``
    invariant enforces same-group anchoring and ``modifier.sort_key >
    anchor.sort_key``, so any non-None subgroup must name a registered
    canonical in the same group.

    ``systems`` records which provider rosters include this feature.
    Used by import-time mappings and the bake script's completeness
    check.

    ``uses`` records which display / classifier subsystem reads the
    feature, so vowels.py / consonants.py / laryngeal display consult
    the registry instead of carrying their own feature-name sets.

    ``is_suprasegmental`` mirrors the existing
    ``SUPRASEGMENTAL_FEATURES`` membership.
    """

    canonical: str
    sort_key: int
    group: str
    aliases: tuple[str, ...] = ()
    subgroup: str | None = None
    systems: frozenset[str] = field(default_factory=frozenset)
    uses: frozenset[str] = field(default_factory=frozenset)
    is_suprasegmental: bool = False


# ---------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------

# ``sort_key`` blocks:
#   100s = Major Class
#   200s = Laryngeal
#   300s = Manner
#   400s = Place (with anchor-modifier adjacency)
#   500s = Tongue-Root / Pharyngeal
#   600s = Prosodic
#
# Gaps between entries leave room to insert new features in the
# right neighbourhood without renumbering. Within a block, the
# legacy ``FEATURE_ORDER`` ordering is preserved so the derived
# table's membership matches the prior structure, modulo Place's
# anchor-first re-ordering (Labial then Round then Labiodental).
_ALL_THREE = frozenset({SYSTEM_HAYES, SYSTEM_PHOIBLE, SYSTEM_PANPHON})
_HAYES_PHOIBLE = frozenset({SYSTEM_HAYES, SYSTEM_PHOIBLE})
_PHOIBLE_ONLY = frozenset({SYSTEM_PHOIBLE})
_HAYES_ONLY = frozenset({SYSTEM_HAYES})

FEATURE_REGISTRY: dict[str, FeatureMetadata] = {
    # --- Major class (100s) ---
    "syllabic": FeatureMetadata(
        canonical="syllabic",
        sort_key=100,
        group=GROUP_MAJOR_CLASS,
        aliases=("Syllabic", "syl"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "consonantal": FeatureMetadata(
        canonical="consonantal",
        sort_key=101,
        group=GROUP_MAJOR_CLASS,
        aliases=("Consonantal", "cons"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "sonorant": FeatureMetadata(
        canonical="sonorant",
        sort_key=102,
        group=GROUP_MAJOR_CLASS,
        aliases=("Sonorant", "son"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "approximant": FeatureMetadata(
        canonical="approximant",
        sort_key=103,
        group=GROUP_MAJOR_CLASS,
        aliases=("Approximant",),
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    # --- Laryngeal (200s) ---
    "voice": FeatureMetadata(
        canonical="voice",
        sort_key=200,
        group=GROUP_LARYNGEAL,
        aliases=("Voice", "voi", "voiced", "periodicGlottalSource"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_LARYNGEAL, USE_NATURAL_CLASS}),
    ),
    "spreadgl": FeatureMetadata(
        canonical="spreadgl",
        sort_key=201,
        group=GROUP_LARYNGEAL,
        aliases=("SpreadGl", "sg", "spreadGlottis", "spread_glottis", "s.g."),
        systems=_ALL_THREE,
        uses=frozenset({USE_LARYNGEAL, USE_NATURAL_CLASS}),
    ),
    "constrgl": FeatureMetadata(
        canonical="constrgl",
        sort_key=202,
        group=GROUP_LARYNGEAL,
        aliases=(
            "ConstrGl",
            "cg",
            "constrictedGlottis",
            "constricted_glottis",
            "c.g.",
        ),
        systems=_ALL_THREE,
        uses=frozenset({USE_LARYNGEAL, USE_NATURAL_CLASS}),
    ),
    "epilaryngealsource": FeatureMetadata(
        canonical="epilaryngealsource",
        sort_key=203,
        group=GROUP_LARYNGEAL,
        aliases=("EpilaryngealSource", "epilaryngealSource"),
        # Anchored to ``voice``: epilaryngeal source is the
        # tier-internal correlate of laryngeal voicing, distinguishing
        # supra-glottal from glottal voice (Esling 2005). PHOIBLE
        # treats it as a refinement of the voicing dimension, so it
        # reads as a child of ``voice`` in the Feature Pane.
        subgroup="voice",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL}),
    ),
    "fortis": FeatureMetadata(
        canonical="fortis",
        sort_key=204,
        group=GROUP_LARYNGEAL,
        aliases=("Fortis",),
        # Fortis / lenis are the energetic-effort axis under voicing.
        # Anchoring them to ``voice`` clusters them with their
        # phonetic correlate rather than leaving them un-rooted at the
        # bottom of the Laryngeal group.
        subgroup="voice",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL}),
    ),
    "lenis": FeatureMetadata(
        canonical="lenis",
        sort_key=205,
        group=GROUP_LARYNGEAL,
        aliases=("Lenis",),
        subgroup="voice",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL}),
    ),
    "raisedlarynxejective": FeatureMetadata(
        canonical="raisedlarynxejective",
        sort_key=206,
        group=GROUP_LARYNGEAL,
        aliases=("RaisedLarynxEjective", "raisedLarynxEjective"),
        # Anchored to ``constrgl``: ejectives are constricted-glottis
        # with a raised larynx. The PHOIBLE feature is the airstream
        # mechanism producing an ejective from the constricted-glottis
        # base, so it's structurally a child of ``constrgl``.
        subgroup="constrgl",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL}),
    ),
    "loweredlarynximplosive": FeatureMetadata(
        canonical="loweredlarynximplosive",
        sort_key=207,
        group=GROUP_LARYNGEAL,
        aliases=("LoweredLarynxImplosive", "loweredLarynxImplosive"),
        # Implosives are constricted-glottis with a lowered larynx;
        # mirror anchor of ``raisedlarynxejective``.
        subgroup="constrgl",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL}),
    ),
    "breathy": FeatureMetadata(
        canonical="breathy",
        sort_key=208,
        group=GROUP_LARYNGEAL,
        aliases=("Breathy", "breathy_voice", "breathyvoice", "breathyVoice"),
        # Breathy / creaky are phonation types that modify the
        # ``voice`` dimension. Anchoring them here keeps the
        # phonation-modifier subcluster contiguous in the pane.
        subgroup="voice",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL, USE_VOWEL_PAIR}),
    ),
    "creaky": FeatureMetadata(
        canonical="creaky",
        sort_key=209,
        group=GROUP_LARYNGEAL,
        aliases=("Creaky", "creaky_voice", "creakyvoice", "creakyVoice"),
        subgroup="voice",
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_LARYNGEAL, USE_VOWEL_PAIR}),
    ),
    # --- Manner (300s) ---
    "continuant": FeatureMetadata(
        canonical="continuant",
        sort_key=300,
        group=GROUP_MANNER,
        aliases=("Continuant", "cont"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "strident": FeatureMetadata(
        canonical="strident",
        sort_key=301,
        group=GROUP_MANNER,
        aliases=("Strident", "strid"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "delrel": FeatureMetadata(
        canonical="delrel",
        sort_key=302,
        group=GROUP_MANNER,
        aliases=(
            "DelRel",
            "delayedRelease",
            "delayed_release",
            "del.rel.",
            "del_rel",
            "del-rel",
        ),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "nasal": FeatureMetadata(
        canonical="nasal",
        sort_key=303,
        group=GROUP_MANNER,
        aliases=("Nasal", "nas", "nasalized", "nasality"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_VOWEL_PAIR, USE_NATURAL_CLASS}),
    ),
    "lateral": FeatureMetadata(
        canonical="lateral",
        sort_key=304,
        group=GROUP_MANNER,
        aliases=("Lateral", "lat"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "trill": FeatureMetadata(
        canonical="trill",
        sort_key=305,
        group=GROUP_MANNER,
        aliases=("Trill",),
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "tap": FeatureMetadata(
        canonical="tap",
        sort_key=306,
        group=GROUP_MANNER,
        aliases=("Tap", "flap"),
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    # Clicks are the velaric-airstream consonants. Hayes names the
    # feature "Click"; PHOIBLE and PanPhon name it "Velaric" (PHOIBLE
    # bakes its "click" column to that label). One canonical so the
    # consonant classifier's ``click`` check catches segments from
    # every source, not only Hayes-authored ones.
    "click": FeatureMetadata(
        canonical="click",
        sort_key=307,
        group=GROUP_MANNER,
        aliases=("Click", "Velaric"),
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "rhotic": FeatureMetadata(
        canonical="rhotic",
        sort_key=309,
        group=GROUP_MANNER,
        aliases=(
            "Rhotic",
            "rhotacized",
            "r_colored",
            "r-colored",
            "rcolored",
            "rcoloured",
        ),
        systems=frozenset(),
        uses=frozenset({USE_VOWEL_PAIR}),
    ),
    # --- Place (400s) with anchor-modifier adjacency ---
    "labial": FeatureMetadata(
        canonical="labial",
        sort_key=400,
        group=GROUP_PLACE,
        aliases=("LABIAL", "Labial", "lab"),
        subgroup="labial",
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "round": FeatureMetadata(
        canonical="round",
        sort_key=401,
        group=GROUP_PLACE,
        aliases=("Round", "rounded"),
        subgroup="labial",
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "labiodental": FeatureMetadata(
        canonical="labiodental",
        sort_key=402,
        group=GROUP_PLACE,
        aliases=("Labiodental",),
        subgroup="labial",
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_CONSONANT}),
    ),
    "coronal": FeatureMetadata(
        canonical="coronal",
        sort_key=410,
        group=GROUP_PLACE,
        aliases=("CORONAL", "Coronal", "cor"),
        subgroup="coronal",
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "anterior": FeatureMetadata(
        canonical="anterior",
        sort_key=411,
        group=GROUP_PLACE,
        aliases=("Anterior", "ant"),
        subgroup="coronal",
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT, USE_NATURAL_CLASS}),
    ),
    "distributed": FeatureMetadata(
        canonical="distributed",
        sort_key=412,
        group=GROUP_PLACE,
        aliases=("Distributed", "distr"),
        subgroup="coronal",
        systems=_ALL_THREE,
        uses=frozenset({USE_CONSONANT}),
    ),
    "dorsal": FeatureMetadata(
        canonical="dorsal",
        sort_key=420,
        group=GROUP_PLACE,
        aliases=("DORSAL", "Dorsal"),
        subgroup="dorsal",
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_CONSONANT, USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "high": FeatureMetadata(
        canonical="high",
        sort_key=421,
        group=GROUP_PLACE,
        aliases=("High", "hi"),
        subgroup="dorsal",
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "low": FeatureMetadata(
        canonical="low",
        sort_key=422,
        group=GROUP_PLACE,
        aliases=("Low", "lo"),
        subgroup="dorsal",
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "back": FeatureMetadata(
        canonical="back",
        sort_key=423,
        group=GROUP_PLACE,
        aliases=("Back",),
        subgroup="dorsal",
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "front": FeatureMetadata(
        canonical="front",
        sort_key=424,
        group=GROUP_PLACE,
        aliases=("Front",),
        subgroup="dorsal",
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    # --- Tongue-Root / Pharyngeal (500s) ---
    # No subgroup anchor: the Tongue-Root group entries are
    # independent dimensions (pharyngeal cavity, tongue-root position,
    # tense) with no phonologically privileged anchor among
    # themselves. The 500-504 sort_keys give the group its natural
    # reading order. The contract
    # ``test_modifiers_sort_directly_after_their_anchor`` requires any
    # non-None ``subgroup`` to point at a registered canonical, which
    # is the right discipline elsewhere.
    "constrpharynx": FeatureMetadata(
        canonical="constrpharynx",
        sort_key=500,
        group=GROUP_TONGUE_ROOT,
        aliases=("ConstrPharynx",),
        systems=_HAYES_ONLY,
        uses=frozenset({USE_NATURAL_CLASS}),
    ),
    "pharyngeal": FeatureMetadata(
        canonical="pharyngeal",
        sort_key=501,
        group=GROUP_TONGUE_ROOT,
        aliases=("Pharyngeal",),
        systems=_HAYES_ONLY,
        uses=frozenset({USE_NATURAL_CLASS}),
    ),
    "atr": FeatureMetadata(
        canonical="atr",
        sort_key=502,
        group=GROUP_TONGUE_ROOT,
        aliases=("ATR", "advancedTongueRoot", "advanced_tongue_root"),
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "tense": FeatureMetadata(
        canonical="tense",
        sort_key=503,
        group=GROUP_TONGUE_ROOT,
        aliases=("Tense",),
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    "rtr": FeatureMetadata(
        canonical="rtr",
        sort_key=504,
        group=GROUP_TONGUE_ROOT,
        aliases=("RTR", "retractedTongueRoot", "retracted_tongue_root"),
        systems=_PHOIBLE_ONLY,
        uses=frozenset({USE_VOWEL, USE_NATURAL_CLASS}),
    ),
    # --- Prosodic / suprasegmental (600s) ---
    "long": FeatureMetadata(
        canonical="long",
        sort_key=600,
        group=GROUP_PROSODIC,
        aliases=("Long",),
        systems=_ALL_THREE,
        uses=frozenset({USE_VOWEL_PAIR}),
        is_suprasegmental=True,
    ),
    "short": FeatureMetadata(
        canonical="short",
        sort_key=601,
        group=GROUP_PROSODIC,
        aliases=("Short",),
        systems=_PHOIBLE_ONLY,
        uses=frozenset(),
        is_suprasegmental=True,
    ),
    "stress": FeatureMetadata(
        canonical="stress",
        sort_key=602,
        group=GROUP_PROSODIC,
        aliases=("Stress",),
        systems=_HAYES_PHOIBLE,
        uses=frozenset(),
        is_suprasegmental=True,
    ),
    # ``tone`` is the generic "this is a tone-bearing element" marker.
    # PHOIBLE bakes its ``tone`` column to this; every tone letter, high
    # OR low, carries it, so it marks tonality, not pitch height.
    "tone": FeatureMetadata(
        canonical="tone",
        sort_key=603,
        group=GROUP_PROSODIC,
        aliases=("Tone",),
        systems=_HAYES_PHOIBLE,
        uses=frozenset({USE_VOWEL_PAIR}),
        is_suprasegmental=True,
    ),
    # Pitch level, the feature that separates a high tone from a low one
    # (PanPhon's ``hitone``). With ``highregister`` it distinguishes the
    # tone levels; a source that ships only the generic ``tone`` marker
    # leaves every tone the same.
    "hightone": FeatureMetadata(
        canonical="hightone",
        sort_key=604,
        group=GROUP_PROSODIC,
        aliases=("HighTone", "hitone"),
        systems=frozenset({SYSTEM_PANPHON}),
        uses=frozenset(),
        is_suprasegmental=True,
    ),
    # Pitch register, the other tone-distinguishing dimension. Hayes
    # writes it ``UpperRegister``, PanPhon ``HighRegister`` / ``hireg``;
    # one canonical for the single upper-vs-lower-band concept.
    "highregister": FeatureMetadata(
        canonical="highregister",
        sort_key=605,
        group=GROUP_PROSODIC,
        aliases=("HighRegister", "hireg", "UpperRegister"),
        systems=frozenset({SYSTEM_PANPHON, SYSTEM_HAYES}),
        uses=frozenset(),
        is_suprasegmental=True,
    ),
}


# ---------------------------------------------------------------------
# Alias index (built once at import; resolves every surface form to
# its canonical key).
# ---------------------------------------------------------------------


def _build_alias_index() -> dict[str, str]:
    """Map every alias and canonical to the canonical key.

    Each entry's aliases and canonical map to that canonical, folded
    case-insensitively and delimiter-insensitively (the same folding
    :py:func:`phonology_shared.data.inventory.normalize_feature_key`
    uses on the engine side). Stored keys are pre-folded so
    :py:func:`resolve_canonical` looks up in one dict access without
    re-folding the input each time.
    """
    index: dict[str, str] = {}
    for meta in FEATURE_REGISTRY.values():
        # The canonical form is already pre-folded, identity-mapped so
        # resolve_canonical("labial") returns "labial".
        index[meta.canonical] = meta.canonical
        for alias in meta.aliases:
            folded = fold_feature_name(alias)
            existing = index.get(folded)
            if existing is not None and existing != meta.canonical:
                raise ValueError(
                    f"alias {alias!r} (folded={folded!r}) maps to two "
                    f"canonical names: {existing!r} and {meta.canonical!r}"
                )
            index[folded] = meta.canonical
    return index


def fold_feature_name(s: str) -> str:
    """Lowercase + strip delimiter characters (``.``, ``_``, space,
    ``-``). The single fold both the registry's alias index and the
    fallback path of
    :py:func:`phonology_shared.data.inventory.normalize_feature_key`
    use, so the engine and the renderer cannot drift on what counts
    as the same spelling.
    """
    k = s.lower()
    return (
        k.replace(".", "").replace("_", "").replace(" ", "").replace("-", "")
    )


_ALIAS_INDEX: Mapping[str, str] = _build_alias_index()


# ---------------------------------------------------------------------
# Public resolver helpers
# ---------------------------------------------------------------------


@lru_cache(maxsize=512)
def resolve_canonical(raw_name: str) -> str | None:
    """Return the canonical key for ``raw_name`` if the registry
    knows it; otherwise ``None``.

    Case-insensitive, delimiter-insensitive: ``LABIAL``, ``Labial``,
    ``labial``, ``lab`` all return ``"labial"``. ``del.rel.``,
    ``delayed_release``, ``DelRel`` all return ``"delrel"``.

    Memoized; the bounded set of feature names sees this hit
    thousands of times across a typical render.
    """
    return _ALIAS_INDEX.get(fold_feature_name(raw_name))


def metadata_for(raw_name: str) -> FeatureMetadata | None:
    """Return the full :py:class:`FeatureMetadata` for any surface
    form of a registered feature, or ``None`` for unknown names."""
    canonical = resolve_canonical(raw_name)
    if canonical is None:
        return None
    return FEATURE_REGISTRY[canonical]


def feature_sort_key(raw_name: str) -> int:
    """Sort position for ``raw_name``. Unknown names trail at the
    end (sort_key == ``len(FEATURE_REGISTRY)``) matching the prior
    behaviour of
    :py:func:`phonology_shared.presentation.constants.sort_features`.
    """
    meta = metadata_for(raw_name)
    if meta is None:
        return len(FEATURE_REGISTRY) * 100
    return meta.sort_key


def is_suprasegmental(raw_name: str) -> bool:
    """``True`` iff the registry tags this feature suprasegmental.
    Unknown names default to ``False`` (segmental until proven
    otherwise: matches the prior behaviour of
    ``SUPRASEGMENTAL_FEATURES`` set membership).
    """
    meta = metadata_for(raw_name)
    return bool(meta and meta.is_suprasegmental)


def features_for_use(use: str) -> frozenset[str]:
    """Return canonical names of every registry entry tagged with
    ``use``. The vowel-pair display routing reads this set instead
    of carrying its own ``_DISPLAY_CONTRAST_FEATURES`` set; the
    consonant classifier likewise can scope on
    ``USE_NATURAL_CLASS``.
    """
    return frozenset(
        meta.canonical
        for meta in FEATURE_REGISTRY.values()
        if use in meta.uses
    )


def all_aliases(canonical: str) -> tuple[str, ...]:
    """Surface forms registered for ``canonical`` (the canonical
    name plus every alias). Used by derived-table editors in
    :py:mod:`phonology_shared.presentation.constants`."""
    meta = FEATURE_REGISTRY.get(canonical)
    if meta is None:
        return ()
    return (meta.canonical, *meta.aliases)


def iter_aliases_in_group(group: str) -> Iterable[str]:
    """All surface forms (canonical + aliases) of every registry
    entry tagged with ``group``, sorted by ``sort_key``. Used to
    derive the ``FEATURE_GROUPS`` table in
    :py:mod:`phonology_shared.presentation.constants`."""
    for meta in sorted(
        (m for m in FEATURE_REGISTRY.values() if m.group == group),
        key=lambda m: m.sort_key,
    ):
        yield meta.canonical
        yield from meta.aliases


# ---------------------------------------------------------------------
# Glossary links
#
# The INLP Linguistic Glossary (https://inlpglossary.ca/) hosts a
# dedicated distinctive-feature page per term at ``/<slug>/``. This
# table maps a registry canonical to that slug for the ~27 features
# that have an entry, turning their names into clickable teaching
# links. Features with no glossary entry are simply absent here and
# render as plain, non-clickable text ("put bad in, get bad out": no
# invented links). Notes: ATR and RTR both point at the single
# tongue-root page; HighTone folds into the general tone page. Slugs
# were verified against the site's sitemap, and every key is asserted
# to be a real canonical by ``test_feature_metadata``.
# ---------------------------------------------------------------------
GLOSSARY_BASE_URL = "https://inlpglossary.ca/"

_GLOSSARY_SLUGS: dict[str, str] = {
    # Major class
    "syllabic": "syllabic",
    "consonantal": "consonantal",
    "sonorant": "sonorant",
    "approximant": "approximant",
    # Laryngeal
    "voice": "voice",
    "spreadgl": "spread-glottis",
    "constrgl": "constricted-glottis",
    # Manner
    "continuant": "continuant",
    "strident": "strident",
    "delrel": "delayed-release",
    "nasal": "nasal",
    "lateral": "lateral",
    # Place
    "labial": "labial",
    "round": "round",
    "coronal": "coronal",
    "anterior": "anterior",
    "distributed": "distributed",
    "dorsal": "dorsal",
    "high": "high",
    "low": "low",
    "back": "back",
    "pharyngeal": "pharyngeal",
    # Tongue-root
    "atr": "advanced-tongue-root",
    "rtr": "advanced-tongue-root",
    "tense": "tense",
    # Prosodic
    "tone": "tone",
    "hightone": "tone",
}


def glossary_url_for(raw_name: str) -> str | None:
    """Return the INLP glossary URL for ``raw_name`` if the feature has
    a glossary entry, else ``None``.

    Accepts any surface form (resolves through
    :py:func:`resolve_canonical`), so display spellings like ``DelRel``,
    ``SpreadGl``, or ``Spread Glottis`` all map to the right page, and
    unknown names return ``None`` without raising.
    """
    canonical = resolve_canonical(raw_name)
    if canonical is None:
        return None
    slug = _GLOSSARY_SLUGS.get(canonical)
    if slug is None:
        return None
    return f"{GLOSSARY_BASE_URL}{slug}/"
