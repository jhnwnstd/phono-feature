"""Shared color palettes for the GUI.

``C`` is the active palette, mutated in place by ``set_theme`` so
existing imports keep observing the current theme. Per-widget
``apply_theme`` methods do the rest of the live swap.

Neutrals avoid pure black and pure white (less glare, contrast above
WCAG AA on body text); accent and status colors are tuned per theme.
"""

from __future__ import annotations

from enum import StrEnum


class Theme(StrEnum):
    """Light vs dark palette axis. StrEnum so existing string call
    sites (``set_theme("light")``) keep working while typed callers
    use :py:attr:`Theme.LIGHT` for discoverability and mypy support.
    """

    LIGHT = "light"
    DARK = "dark"


class PaletteMode(StrEnum):
    """Standard vs colorblind-friendly palette axis. Independent of
    :py:class:`Theme`; both axes compose to produce the four
    concrete palette tables (LIGHT, DARK, COLORBLIND_LIGHT,
    COLORBLIND_DARK)."""

    STANDARD = "standard"
    COLORBLIND = "colorblind"


class ClassState(StrEnum):
    """Natural-class verdict for the analysis panel's Class tab.
    Drives both the tab's colour cue and the
    :py:func:`class_state_palette_keys` mapping that resolves into
    palette role keys for both clients."""

    NATURAL = "natural"
    NOT_NATURAL = "not_natural"
    NEUTRAL = "neutral"


LIGHT = {
    # Neutrals (Material-ish: warm light gray, not blueish)
    "bg": "#F7F7F7",
    "panel": "#FFFFFF",
    "border": "#DADCE0",
    "text": "#202124",
    "text_dim": "#5F6368",
    # Status cues for the builder's live cap counter: amber as a
    # count nears its cap, red once it is at/over. Shared so the
    # desktop QLabel and the web counter (relayed to CSS) agree.
    "status_warn": "#B45309",
    "status_error": "#B91C1C",
    # Accent + selection
    "accent": "#2563EB",
    "accent_light": "#D6E8FF",
    # Segment-button states
    "seg_default": "#F2F3F5",
    "seg_selected": "#2563EB",
    "seg_matched": "#2563EB",
    "seg_unmatched": "#E2E8F0",
    # Feature value semantics
    "plus": "#15803D",
    "plus_bg": "#DCFCE7",
    "minus": "#B91C1C",
    "minus_bg": "#FEE2E2",
    # Neutral / contrastive cue. In standard mode this re-uses the
    # accent slot (so contrastive rows keep their familiar blue
    # tint); the colorblind palette overrides both keys with a
    # distinct purple so "neither + nor -" no longer collides with
    # the positive blue. Added here so the key set is uniform across
    # palettes and consumers can ``C["neutral"]`` unconditionally.
    "neutral": "#2563EB",
    "neutral_bg": "#D6E8FF",
    "shared_plus": "#DCFCE7",
    "shared_minus": "#FEE2E2",
    # Primary-action and destructive-action buttons (Save / Delete /
    # Create-Grid). Hover is slightly DEEPER than default in light
    # mode so "pressing in" reads as a darker version of the same hue.
    # In dark mode these flip (see DARK) because the dark-mode accent
    # is pale; using it as the default makes the button look washed
    # out and the hover then has to swing to a vivid saturated state
    # for distinction. Both directions should read as "press == more
    # contrast against background".
    "btn_primary": "#2563EB",
    "btn_primary_text": "#FFFFFF",
    # One Tailwind shade past the default (blue-700 to blue-800,
    # red-800 to red-900). Reads as a subtle "press". The original
    # hovers were essentially the default colour, which made the
    # hover state hard to feel.
    "btn_primary_hover": "#1E40AF",
    "btn_primary_hover_text": "#FFFFFF",
    "btn_danger": "#B91C1C",
    "btn_danger_text": "#FFFFFF",
    "btn_danger_hover": "#7F1D1D",
    "btn_danger_hover_text": "#FFFFFF",
    # Disabled-button palette: darker bg than ``tag_gray`` and a
    # heavily muted text colour so the button recedes from the
    # active toolbar buttons. The border matches the bg (no rim)
    # so the disabled state reads as "flat tile, not interactive".
    "btn_disabled_bg": "#E2E4E7",
    "btn_disabled_text": "#9AA0A6",
    "btn_disabled_border": "#E2E4E7",
    # Splitter handle hover: a neutral grey, NOT the accent blue.
    # Accent is reserved for "active / selected" semantics; the
    # drag handle is an "interactive surface" cue, which a darker
    # grey communicates without overloading the selected meaning.
    "splitter_hover": "#9AA0A6",
    # Analysis panel + tag chips
    "analysis_bg": "#F2F3F5",
    "tag_blue": "#DBEAFE",
    "tag_blue_text": "#1D4ED8",
    "tag_green": "#DCFCE7",
    "tag_green_text": "#15803D",
    "tag_red": "#FEE2E2",
    "tag_red_text": "#B91C1C",
    "tag_gray": "#F1F3F4",
    "tag_gray_text": "#5F6368",
    # Neutral-chip slot. Mirrors tag_gray in standard mode so existing
    # rendering is unchanged; the colorblind palette overrides it with
    # a distinct purple to separate "underspec / mixed" from the
    # default-gray "not interactive" cue.
    "tag_purple": "#F1F3F4",
    "tag_purple_text": "#5F6368",
    # Tooltip surface. Floats above the active panel as a high-contrast
    # popover so hover text reads clearly even when the underlying
    # surface is light. Kept dark in BOTH light and dark themes so the
    # tooltip presentation is consistent across themes (the dark-theme
    # tooltip is the visual reference the light theme matches).
    "tooltip_bg": "#202124",
    "tooltip_text": "#F7F7F7",
}

COLORBLIND_LIGHT = {
    # Mapping rule (applied uniformly to every slot):
    #   blue  -> purple  (selected / neutral / accent)
    #   green -> blue    (positive / "+")
    #   red   -> orange  (negative / "-")
    #   gray  stays gray (default / inactive)
    # Wong-derived hues so the four families are perceptually
    # distinct under deuteranopia, protanopia, and tritanopia.
    "bg": "#F7F7F7",
    "panel": "#FFFFFF",
    "border": "#DADCE0",
    "text": "#202124",
    "text_dim": "#5F6368",
    # Cap-counter status cues: orange (warn) and vermillion (error),
    # kept in the Wong-derived warm family so they stay distinct
    # under deuteranopia / protanopia.
    "status_warn": "#E69F00",
    "status_error": "#D55E00",
    # Accent matches ``seg_selected`` so the brand colour and the
    # selected-segment colour stay visually unified.
    "accent": "#CC79A7",
    "accent_light": "#F3D6E8",
    # Segment-button states
    "seg_default": "#F2F3F5",
    "seg_selected": "#CC79A7",
    "seg_matched": "#CC79A7",
    "seg_unmatched": "#E2E8F0",
    # Feature value semantics: plus=blue, minus=orange, neutral=purple
    "plus": "#0072B2",
    "plus_bg": "#D6E8FF",
    "minus": "#E69F00",
    "minus_bg": "#FFE8B5",
    "neutral": "#CC79A7",
    "neutral_bg": "#F3D6E8",
    "shared_plus": "#D6E8FF",
    "shared_minus": "#FFE8B5",
    # Primary buttons share the accent; danger stays orange.
    "btn_primary": "#CC79A7",
    "btn_primary_text": "#FFFFFF",
    "btn_primary_hover": "#9A4F7F",
    "btn_primary_hover_text": "#FFFFFF",
    "btn_danger": "#E69F00",
    "btn_danger_text": "#202124",
    "btn_danger_hover": "#B87900",
    "btn_danger_hover_text": "#FFFFFF",
    "btn_disabled_bg": "#E2E4E7",
    "btn_disabled_text": "#9AA0A6",
    "btn_disabled_border": "#E2E4E7",
    "splitter_hover": "#9AA0A6",
    # Analysis panel and tag chips. ``tag_blue`` (segment slot) is
    # purple because "selected/matched" maps to purple under the new
    # rule; ``tag_green`` (positive slot) is blue; ``tag_red``
    # (negative slot) is orange; ``tag_gray`` and ``tag_purple``
    # stay distinct (gray for default/inactive, purple for the
    # underspec / mixed neutral state).
    "analysis_bg": "#F2F3F5",
    "tag_blue": "#F3D6E8",
    "tag_blue_text": "#9A4F7F",
    "tag_green": "#D6E8FF",
    "tag_green_text": "#0072B2",
    "tag_red": "#FFE8B5",
    "tag_red_text": "#A46300",
    "tag_purple": "#F3D6E8",
    "tag_purple_text": "#9A4F7F",
    "tag_gray": "#F1F3F4",
    "tag_gray_text": "#5F6368",
    # See LIGHT.tooltip_bg comment. Same dark-on-light tooltip in
    # colorblind light so hover popovers stay consistent across modes.
    "tooltip_bg": "#202124",
    "tooltip_text": "#F7F7F7",
}

COLORBLIND_DARK = {
    # Same mapping rule as COLORBLIND_LIGHT (blue -> purple,
    # green -> blue, red -> orange, gray stays gray) applied to
    # the dark-theme value set.
    "bg": "#181818",
    "panel": "#202020",
    "border": "#3A3A3A",
    "text": "#E8EAED",
    "text_dim": "#B8B8B8",
    # Cap-counter status cues (colorblind dark): brightened orange
    # and vermillion so they stay legible on the dark panel and
    # distinct from each other under deuteranopia / protanopia.
    "status_warn": "#F0A202",
    "status_error": "#FF6E40",
    # Accent matches seg_selected.
    "accent": "#D7A0D3",
    "accent_light": "#43243F",
    "seg_default": "#262626",
    "seg_selected": "#9A4F7F",
    "seg_matched": "#9A4F7F",
    "seg_unmatched": "#3A3A3A",
    # Feature value semantics
    "plus": "#56B4E9",
    "plus_bg": "#16384D",
    "minus": "#F0A202",
    "minus_bg": "#4A3100",
    "neutral": "#D7A0D3",
    "neutral_bg": "#43243F",
    "shared_plus": "#16384D",
    "shared_minus": "#4A3100",
    # Buttons. Mirrors the standard-DARK pattern: saturated default
    # (mid-tone purple), pale hover that "lifts" against the dark bg.
    # Was deep blue / pale blue -> deep purple / pale purple.
    "btn_primary": "#9A4F7F",
    "btn_primary_text": "#FFFFFF",
    "btn_primary_hover": "#D7A0D3",
    "btn_primary_hover_text": "#181818",
    "btn_danger": "#9A5B00",
    "btn_danger_text": "#FFFFFF",
    "btn_danger_hover": "#F0A202",
    "btn_danger_hover_text": "#181818",
    "btn_disabled_bg": "#161616",
    "btn_disabled_text": "#6A6A6A",
    "btn_disabled_border": "#161616",
    "splitter_hover": "#6A6A6A",
    # Analysis panel and tag chips. ``tag_blue`` (segment slot) is
    # purple under the new rule; ``tag_green`` (positive) is blue;
    # ``tag_red`` (negative) is orange.
    "analysis_bg": "#262626",
    "tag_blue": "#43243F",
    "tag_blue_text": "#D7A0D3",
    "tag_green": "#16384D",
    "tag_green_text": "#56B4E9",
    "tag_red": "#4A3100",
    "tag_red_text": "#F0A202",
    "tag_purple": "#43243F",
    "tag_purple_text": "#D7A0D3",
    "tag_gray": "#2A2A2A",
    "tag_gray_text": "#B8B8B8",
    # See LIGHT.tooltip_bg comment. Dark theme keeps its current
    # tooltip look (dark panel + light text) so the cross-theme
    # reference stays consistent.
    "tooltip_bg": "#202020",
    "tooltip_text": "#E8EAED",
}

DARK = {
    # Neutrals (true dark gray, not deep navy)
    "bg": "#181818",
    "panel": "#202020",
    "border": "#3A3A3A",
    "text": "#E8EAED",
    "text_dim": "#B8B8B8",
    # Cap-counter status cues (dark): amber as a count nears its cap,
    # a light red once at/over so it stays readable on the dark
    # panel where the light-mode #B91C1C would be too dim.
    "status_warn": "#F0A202",
    "status_error": "#F87171",
    # Accent + selection
    "accent": "#60A5FA",
    "accent_light": "#2F4F6F",
    # Segment-button states
    "seg_default": "#262626",
    "seg_selected": "#3B82F6",
    "seg_matched": "#3B82F6",
    "seg_unmatched": "#3A3A3A",
    # Feature value semantics
    "plus": "#86EFAC",
    "plus_bg": "#14532D",
    "minus": "#FCA5A5",
    "minus_bg": "#7F1D1D",
    # See LIGHT.neutral comment: re-uses accent slot in standard mode;
    # colorblind overrides with purple. Both keys exist in every
    # palette so consumers can read them unconditionally.
    "neutral": "#60A5FA",
    "neutral_bg": "#2F4F6F",
    "shared_plus": "#14532D",
    "shared_minus": "#7F1D1D",
    # See LIGHT.btn_primary comment: in dark mode the saturated deep
    # blue / deep red is the DEFAULT (reads boldly on dark bg), and
    # the pale tint becomes the hover (reads as a "lift"). Hover text
    # switches to dark because white on pale pink / pale blue would
    # smear; everything else stays white on the saturated default.
    "btn_primary": "#1D4ED8",
    "btn_primary_text": "#FFFFFF",
    "btn_primary_hover": "#60A5FA",
    "btn_primary_hover_text": "#181818",
    "btn_danger": "#991B1B",
    "btn_danger_text": "#FFFFFF",
    "btn_danger_hover": "#FCA5A5",
    "btn_danger_hover_text": "#181818",
    # Dark-mode disabled: bg darker than the panel chrome (sinks BELOW
    # the toolbar surface so it reads as "carved out, inactive"), text
    # heavily muted so it is barely legible. The visible cue is the
    # darker tile; the label is just a hint.
    "btn_disabled_bg": "#161616",
    "btn_disabled_text": "#555555",
    "btn_disabled_border": "#161616",
    # See LIGHT.splitter_hover comment. Dark mode wants the hover
    # cue LIGHTER than the resting border so it pops against the
    # dark background; same "neutral, not accent" rule applies.
    "splitter_hover": "#6A6A6A",
    # Analysis panel + tag chips
    "analysis_bg": "#262626",
    "tag_blue": "#1E3A8A",
    "tag_blue_text": "#93C5FD",
    "tag_green": "#14532D",
    "tag_green_text": "#86EFAC",
    "tag_red": "#7F1D1D",
    "tag_red_text": "#FCA5A5",
    "tag_gray": "#2A2A2A",
    "tag_gray_text": "#B8B8B8",
    # See LIGHT.tag_purple comment.
    "tag_purple": "#2A2A2A",
    "tag_purple_text": "#B8B8B8",
    # See LIGHT.tooltip_bg comment. Dark theme's tooltip is the
    # cross-theme visual reference: dark surface, light text.
    "tooltip_bg": "#202020",
    "tooltip_text": "#E8EAED",
}

# Active palette, mutated in place by set_theme / set_palette_mode.
C: dict[str, str] = dict(LIGHT)

# Active palette axes (light/dark and standard/colorblind). ``C`` is
# the product of these two; storing them separately means a mode
# flip preserves the user's light/dark choice and vice versa.
#
# These three (_active_theme, _active_mode, theme_version) are
# intentional module-level mutable state, parallel to ``C`` above.
# Justification: the palette is a process-wide singleton observed by
# every widget; threading it through every consumer as state would
# require a global registry anyway. The test suite resets them via
# the ``_reset_palette_module_state`` fixture in
# ``shared/tests/conftest.py`` so tests do not leak palette state
# across each other.
_active_theme: str = Theme.LIGHT.value
_active_mode: str = PaletteMode.STANDARD.value

# Monotonic counter bumped on every palette change. Caches that
# depend on palette colors key on this integer; on miss they
# rebuild from the current ``C`` and store the new version. Lets
# callers cache derived objects (for example QBrush triples)
# without wiring observer callbacks into ``set_theme``.
theme_version: int = 0


def _resolve(theme: str, mode: str) -> dict[str, str]:
    """Return the palette dict for the given (theme, mode) pair.

    Inputs are coerced through the enum constructors so a misspelled
    string raises ``ValueError`` at the boundary instead of silently
    routing to LIGHT / STANDARD.
    """
    mode_e = PaletteMode(mode)
    theme_e = Theme(theme)
    if mode_e is PaletteMode.COLORBLIND:
        return COLORBLIND_DARK if theme_e is Theme.DARK else COLORBLIND_LIGHT
    return DARK if theme_e is Theme.DARK else LIGHT


def _refresh_active() -> None:
    """Repopulate ``C`` from the current (_active_theme, _active_mode)
    pair and bump ``theme_version`` so cached derivatives invalidate.

    Invariant: ``C`` is mutated in place (``clear()`` + ``update()``),
    never rebound. Modules that did ``from ... import C`` once at
    load time keep observing the live palette without re-importing.
    Replacing the rebind path with ``C = target`` would silently
    leave existing importers pointing at the stale dict.
    """
    global theme_version
    target = _resolve(_active_theme, _active_mode)
    C.clear()
    C.update(target)
    theme_version += 1


#: Accepted ``set_theme`` arguments, derived from :py:class:`Theme`
#: so the enum stays the single source of truth. Both UIs read this
#: as a string set for backward compatibility with callers that
#: predate the enum.
ALLOWED_THEMES: frozenset[str] = frozenset(Theme)
#: Accepted ``set_palette_mode`` arguments, derived from
#: :py:class:`PaletteMode`. Same shared contract.
ALLOWED_PALETTE_MODES: frozenset[str] = frozenset(PaletteMode)


def set_theme(name: str | Theme) -> None:
    """Switch the active palette to "light" or "dark", preserving the
    current standard/colorblind mode.

    Raises :py:class:`ValueError` on unknown names. Both UIs share
    this contract: the web bridge wraps the raise into a
    ``ValidationError``; the desktop validates user-supplied values
    (e.g. ``QSettings`` reads) at the trust boundary before calling
    in. ``Theme(name)`` coerces strings and rejects unknowns with
    the same ValueError the manual check used to raise.
    """
    global _active_theme
    _active_theme = str(Theme(name))
    _refresh_active()


def set_palette_mode(mode: str | PaletteMode) -> None:
    """Switch the active palette between "standard" and "colorblind",
    preserving the current light/dark theme.

    Raises :py:class:`ValueError` on unknown modes. See
    :py:func:`set_theme` for the rationale.
    """
    global _active_mode
    _active_mode = str(PaletteMode(mode))
    _refresh_active()


def get_palette_mode() -> str:
    """Return "standard" or "colorblind" for the active palette."""
    return _active_mode


def get_theme_name() -> str:
    """Return "light" or "dark" for the currently active palette."""
    return _active_theme


#: Accepted natural-class verdict labels, derived from
#: :py:class:`ClassState`. Kept as a string frozenset for callers
#: that predate the enum.
ALLOWED_CLASS_STATES: frozenset[str] = frozenset(ClassState)


def class_state_palette_keys(
    state: str | ClassState,
) -> tuple[str, str] | None:
    """Map a natural-class verdict to the ``(fg_key, bg_key)`` pair
    of palette keys used to paint the Class tab band.

    Returns ``None`` for :py:attr:`ClassState.NEUTRAL` to signal
    "no override; let the tab keep its default palette colours".
    The desktop's :py:func:`_class_state_stylesheet` and the build
    script's CSS-variable bake both consult this helper so the
    verdict-to-palette-role mapping lives in one place. Adding a
    new state means editing :py:class:`ClassState`, extending the
    match below, and adding a CSS rule; no second mapping copy to
    keep in sync.
    """
    coerced = ClassState(state)
    if coerced is ClassState.NATURAL:
        return ("plus", "plus_bg")
    if coerced is ClassState.NOT_NATURAL:
        return ("minus", "minus_bg")
    return None
