"""Shared GUI constants, geometry, and tiny helpers."""

from collections.abc import Iterable, Mapping
from enum import StrEnum

from phonology_shared.presentation import palette as _palette
from phonology_shared.presentation.feature_metadata import (
    FEATURE_REGISTRY,
    GROUP_ORDER,
)
from phonology_shared.presentation.feature_metadata import (
    feature_sort_key as _feature_sort_key,
)
from phonology_shared.presentation.feature_metadata import (
    iter_aliases_in_group,
)
from phonology_shared.presentation.palette import C

SETTINGS_ORG = "features"
SETTINGS_APP = "SegFeatureEngine"

# Unicode minus (U+2212) so the negative-feature glyph matches
# the width and stroke weight of ``+``. Escape (not literal) so
# a future editor cannot quietly replace it with a look-alike.
MINUS_SIGN: str = "\u2212"


class TagColor(StrEnum):
    """Semantic name for an analysis-pane chip colour.

    Magic strings were typo-silent before: ``_tag(text, "bleu")``
    fell back to gray with no warning. This enum is exhaustive (mypy
    can verify every consumer), self-documenting (``TagColor.SEGMENT``
    says WHY the chip is blue), and the string values match the
    historical palette keys so existing lookups keep working.
    """

    SEGMENT = "blue"
    PLUS = "green"
    MINUS = "red"
    NEUTRAL = "gray"


# One source of truth for the inline-chip box model. Every chip in
# the analysis pane shares this geometry; the previous magic numbers
# (``border-radius:4px; padding:2px 7px; ...``) were duplicated in
# every f-string in analysis.py and went out of sync at least once
# during the dark-mode work.
CHIP_BORDER_RADIUS_PX: int = 4
CHIP_PADDING_CSS: str = "2px 7px"
CHIP_MARGIN_PX: int = 2
CHIP_FONT_SIZE_PT: int = 10

# Web-side font-size ladder. The web stylesheet picks values from
# this ladder so a future "make everything one notch larger" change
# is one constant adjustment rather than a CSS sweep. The desktop
# manages its own per-widget point sizing (Qt's QFont API) and only
# references ``FONT_SIZE_MIN_PX`` below to enforce a shared floor
# for the segment-button rasterizer's font-shrink loop. CSS variable
# names mirror these tokens (``--font-size-base`` etc.).
FONT_SIZE_ICON_PX: int = 16
FONT_SIZE_HEADING_PX: int = 15
FONT_SIZE_BASE_PX: int = 14
FONT_SIZE_CONTROL_PX: int = 13
FONT_SIZE_META_PX: int = 12
FONT_SIZE_LABEL_PX: int = 11
FONT_SIZE_MICRO_PX: int = 10
# Lower bound on the rasterizer's font-shrink search (see
# ``rasterizeText`` in ``web/main.js``) and any future Qt-side
# text-fit logic. Below 10 px, combining marks (the diacritics that
# turn ``o`` into ``o̞`` or ``a`` into ``ã``) stop reading cleanly
# regardless of font choice; the seg-btn is then better off letting
# the glyph clip slightly than shrinking the font further. PHOIBLE
# inventories have far more combining-mark + multi-codepoint glyphs
# than the bundled curated inventories (Korean PHOIBLE alone has
# stacked ``o̞̜``), so a tighter floor benefits PHOIBLE without
# being PHOIBLE-specific. Pixel-only because the rasterizer walks
# the CSS ``font-size`` string in px steps.
FONT_SIZE_MIN_PX: int = 10

# Accessible name announced by screen readers when focus lands
# on the chart container (web aria-label / Qt accessibleName).
VOWEL_CHART_ACCESSIBLE_NAME: str = "IPA vowel chart"


def format_segment_accessible_label(seg: str) -> str:
    """Format a segment glyph for screen-reader announcement.

    The slashed form ``/x/`` matches the IPA convention for a
    phoneme and is what assistive tech reads aloud. Both renderers
    set this on every pooled / created seg button: web via
    ``btn.setAttribute("aria-label", ...)``, desktop via
    ``btn.setAccessibleName(...)``.
    """
    return f"/{seg}/"


# Bundled-inventory stem the web boots into and that build.py
# precomputes the bootstrap render for. Single source so the
# build-time bootstrap and the runtime default cannot drift. Must
# name a TRACKED inventory: copy_inventories omits gitignored files
# from the runtime manifest, so a gitignored stem would still bake
# into the bootstrap chart yet be missing at runtime, silently
# dropping the default-pick to the first bundled inventory.
DEFAULT_INVENTORY_STEM: str = "hayes_features"


def inventory_sort_key(fname: str, label: str) -> tuple[int, str]:
    """Dropdown ordering key shared by the web manifest build and the
    desktop inventory combo so both list inventories in the same order.

    The canonical Hayes (2009) inventories lead the list: the universal
    default (:data:`DEFAULT_INVENTORY_STEM`) first, then any other
    Hayes inventory, then everything else alphabetically by display
    label.
    """
    stem = fname[:-5] if fname.endswith(".json") else fname
    if stem == DEFAULT_INVENTORY_STEM:
        rank = 0
    elif "hayes" in label.casefold():
        rank = 1
    else:
        rank = 2
    return (rank, label.casefold())


# Hover-tooltip strings for the wildcard ("Allow underspecified")
# matching-mode toggle that sits in the Features pane header on
# both UIs. ``STRICT_ACTIVE`` runs when the button is NOT pressed
# (the click would enable wildcard); ``WILDCARD_ACTIVE`` when the
# button IS pressed (the click would revert to strict). Single
# source so the desktop's ``setToolTip`` and the web's ``title``
# attribute read identically; the web relays via the inlined
# STATUS_TEXT JSON.
MATCH_MODE_TOOLTIP_STRICT_ACTIVE: str = (
    "Allow underspecified feature matches: segments with 0 or "
    "absent values can form a natural class when no other valued "
    "feature explicitly contradicts it."
)
MATCH_MODE_TOOLTIP_WILDCARD_ACTIVE: str = (
    "Switch to strict matching (only explicit +/- values match)."
)

# Placeholder copy for non-ideal states. Each string is shown in
# place of an empty result so the user always sees something
# orienting rather than a blank region. Tone matches the rest of
# the status copy: short, lowercase, never alarming.
EMPTY_NATURAL_CLASS_HINT: str = "No natural class matches this selection."
EMPTY_SHARED_FEATURES_HINT: str = "No features shared across this selection."
EMPTY_PHOIBLE_SEARCH_HINT: str = "No PHOIBLE inventories match this query."

# Monospace font fallback chain for IPA-heavy text (analysis-pane
# chips, anything rendering segment symbols / feature values). Order:
# most-IPA-coverage first, then per-OS defaults that are usually
# installed, then the system ``monospace`` alias as a last resort.
# Without an explicit chain Qt resolves ``monospace`` to whatever the
# system aliases, which on stripped-down Linux can land on a font with
# poor coverage of combining marks like U+0361 (the tie bar in d͡ʒ).
# Python list, usable with ``QFont.setFamilies``. ``MONO_FAMILY_CSS``
# is the CSS string form for inline ``font-family:`` rules.
MONO_FAMILIES: list[str] = [
    "Noto Sans Mono",
    "DejaVu Sans Mono",
    "Menlo",
    "Consolas",
    "Liberation Mono",
    "monospace",
]
# CSS uses double quotes around family names with spaces; this keeps
# the string safe to embed inside ``style='...'`` HTML attributes
# (single-quoted on the outside). CSS accepts either quote style for
# strings; double quotes here avoid colliding with our inline-style
# attribute convention.
MONO_FAMILY_CSS: str = ", ".join(
    f'"{f}"' if " " in f else f for f in MONO_FAMILIES
)


_tag_palettes_cache: tuple[int, dict[TagColor, tuple[str, str]]] | None = None


def tag_palettes() -> dict[TagColor, tuple[str, str]]:
    """Inline-chip ``(background, foreground)`` palette keyed by
    :class:`TagColor`.

    Memoised on :py:data:`phonology_shared.presentation.palette.theme_version`
    so the analysis pane's chip rendering (which calls this thousands
    of times per click via :py:func:`_tag`) doesn't pay for eight
    dict lookups + a fresh dict + four fresh tuples per call. A
    theme toggle bumps ``theme_version`` and invalidates the cache.
    """
    global _tag_palettes_cache
    version = _palette.theme_version
    if _tag_palettes_cache is not None and _tag_palettes_cache[0] == version:
        return _tag_palettes_cache[1]
    built: dict[TagColor, tuple[str, str]] = {
        TagColor.SEGMENT: (C["tag_blue"], C["tag_blue_text"]),
        TagColor.PLUS: (C["tag_green"], C["tag_green_text"]),
        TagColor.MINUS: (C["tag_red"], C["tag_red_text"]),
        TagColor.NEUTRAL: (C["tag_gray"], C["tag_gray_text"]),
    }
    _tag_palettes_cache = (version, built)
    return built


# Pre-baked inline-chip ``<span style='...'>`` prefix per (theme_version,
# color). The hot path through ``_tag`` in analysis.py used to
# interpolate 9 fields (bg, fg, 5 invariant CSS constants, etc.) per
# call; the only thing that actually varies per (theme, color) is the
# bg/fg pair, so the prefix is fully cacheable. Cache keyed on
# ``palette.theme_version`` so a theme toggle invalidates it.
_TAG_PREFIX_CACHE: dict[tuple[int, TagColor], str] = {}


def tag_prefix(colour: TagColor) -> str:
    """Return the pre-baked ``<span style='...'>`` prefix for ``colour``.

    Callers concatenate ``tag_prefix(colour) + escaped_text + "</span>"``
    instead of paying for a 9-field f-string interpolation per call.
    """
    version = _palette.theme_version
    key = (version, colour)
    cached = _TAG_PREFIX_CACHE.get(key)
    if cached is not None:
        return cached
    palette = tag_palettes()
    bg, fg = palette.get(colour, palette[TagColor.NEUTRAL])
    prefix = (
        f"<span style='background:{bg}; color:{fg};"
        f" border-radius:{CHIP_BORDER_RADIUS_PX}px;"
        f" padding:{CHIP_PADDING_CSS};"
        f" margin:{CHIP_MARGIN_PX}px;"
        f" font-family:{MONO_FAMILY_CSS};"
        f" font-size:{CHIP_FONT_SIZE_PT}pt;"
        f" white-space:nowrap;'>"
    )
    _TAG_PREFIX_CACHE[key] = prefix
    return prefix


BTN_W = 33
BTN_GAP = 4

# ---------------------------------------------------------------------
# Derived tables: single source of truth lives in
# :py:mod:`phonology_shared.presentation.feature_metadata`.
#
# ``FEATURE_ORDER``, ``FEATURE_GROUPS``, and ``SUPRASEGMENTAL_FEATURES``
# preserve their previous module-level names so existing consumers
# (the desktop ``_populate_features`` loop, the view-model's
# ``_grouped_features``, the analysis renderer's contrast-row sort,
# the consonant-grouper tone guard, the suprasegmental tests) keep
# working unchanged. Each table is now computed from
# :py:data:`FEATURE_REGISTRY` at import: one entry per concept, with
# every surface form (``LABIAL`` / ``Labial`` / ``lab`` / ...)
# enumerated in the entry's ``aliases``. That collapses the prior
# hand-maintained duplication and gives ``sort_features`` a real
# canonical lookup so case variants of the same concept always
# land at the same position.
# ---------------------------------------------------------------------

#: Feature ordering: every surface form of every registry entry,
#: sorted by the entry's ``sort_key``. Place modifiers (Round,
#: Anterior, High, ...) sort directly after their anchor (Labial,
#: Coronal, Dorsal) by design. Unknown features (anything not
#: registered) trail at the end: :py:func:`sort_features` handles
#: that fallback via :py:func:`feature_sort_key`.
FEATURE_ORDER: list[str] = [
    alias
    for meta in sorted(FEATURE_REGISTRY.values(), key=lambda m: m.sort_key)
    for alias in (meta.canonical, *meta.aliases)
]

#: Two-column feature panel layout. Each entry is
#: ``(group_title, member_features)``. The member list collects
#: every surface form of every registry entry tagged with that
#: group, in ``sort_key`` order: so an inventory that ships either
#: ``LABIAL`` (Hayes) or ``Labial`` (PHOIBLE) sees its feature
#: routed to the Place group correctly.
FEATURE_GROUPS: list[tuple[str, list[str]]] = [
    (group_name, list(iter_aliases_in_group(group_name)))
    for group_name in GROUP_ORDER
]

#: Features the literature treats as TIER-SEPARATE from the
#: segmental core (autosegmental phonology, 2024 CLTS vector work).
#: Now derived from the registry's ``is_suprasegmental`` flag, with
#: every surface alias included so consumers can do plain set
#: membership against any case variant.
#:
#: Two load-bearing consumers:
#:
#: - :py:func:`phonology_shared.chart.consonants.is_member`'s
#:   tone-phoneme guard.
#: - Renderers that scope natural-class queries away from the
#:   suprasegmental tier.
#:
#: Membership here is NOT a parallel concept to
#: :py:data:`FEATURE_ORDER`; the registry maintains both
#: independently (a feature can be in the Prosodic display group
#: yet not on the suprasegmental tier, or vice versa).
SUPRASEGMENTAL_FEATURES: frozenset[str] = frozenset(
    alias
    for meta in FEATURE_REGISTRY.values()
    if meta.is_suprasegmental
    for alias in (meta.canonical, *meta.aliases)
)


def sort_features(features: Iterable[str]) -> list[str]:
    """Sort features by their canonical position in
    :py:data:`FEATURE_REGISTRY`. Unknowns trail at the end.

    Aliases of the same canonical name share a sort position, so
    ``sort_features(["LABIAL", "Labial"])`` produces an output
    whose two entries are adjacent regardless of input order.
    """
    return sorted(features, key=_feature_sort_key)


def sort_spec(spec: Mapping[str, str]) -> dict[str, str]:
    """Reorder a feature-bundle into canonical key order. Accepts any
    Mapping (incl. read-only views from the engine bundle cache);
    returns a fresh dict so callers can safely iterate."""
    return {feature: spec[feature] for feature in sort_features(spec)}


def scrollbar_style() -> str:
    """Thin overlay-style scrollbar QSS.

    A function (not a module constant) so theme swaps pick up the new
    palette; an f-string at import time would bake in the old colors.
    """
    return f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
        border: none;
    }}

    QScrollBar::handle:vertical {{
        background: {C["border"]};
        border-radius: 3px;
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {C["text_dim"]};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
        background: none;
        border: none;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
        border: none;
    }}

    QScrollBar::handle:horizontal {{
        background: {C["border"]};
        border-radius: 3px;
        min-width: 24px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {C["text_dim"]};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
        background: none;
        border: none;
    }}

    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}
"""
