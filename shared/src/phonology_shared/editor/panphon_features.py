"""Canonical mapping from PanPhon's short feature names to the
app's canonical names.

Lives in shared/ (not under desktop/) because two consumers depend
on it: (a) the desktop's live
:py:class:`phonology_features.providers.panphon_provider.PanPhonFeatureProvider`
that wraps :py:mod:`panphon` directly, and (b) the build-time bake
script + the runtime lookup provider that ship a JSON snapshot of
PanPhon's IPA table to the web bundle. Centralising the mapping
keeps the desktop and the web in lockstep without forcing either
to depend on the other's package.

Names on the right follow the app's canonical capitalisation
conventions (terminal features title-cased; the matching Hayes
bundle keys are recognised by the engine identically). Ordering
here also fixes the column order of
generated bundles so positional iteration over PanPhon's name
vector pairs values to the right column even when PanPhon adds new
columns in a future release (unknown PanPhon names are skipped
silently rather than raising).
"""

from __future__ import annotations

from collections.abc import Mapping

PANPHON_TO_APP_FEATURE: Mapping[str, str] = {
    "syl": "Syllabic",
    "son": "Sonorant",
    "cons": "Consonantal",
    "cont": "Continuant",
    "delrel": "DelRel",
    "lat": "Lateral",
    "nas": "Nasal",
    "strid": "Strident",
    "voi": "Voice",
    "sg": "SpreadGl",
    "cg": "ConstrGl",
    "ant": "Anterior",
    "cor": "Coronal",
    "distr": "Distributed",
    "lab": "Labial",
    "hi": "High",
    "lo": "Low",
    "back": "Back",
    "round": "Round",
    "velaric": "Velaric",
    "tense": "Tense",
    "long": "Long",
    "hitone": "HighTone",
    "hireg": "HighRegister",
}


def panphon_value_to_app(value: object) -> str:
    """Coerce a single PanPhon feature value to the app's three-
    valued vocabulary.

    PanPhon emits ``"+"`` / ``"-"`` / ``"0"`` from
    :py:meth:`Segment.strings`; the numeric path (``1``, ``-1``,
    ``0``) is supported for forward-compatibility with PanPhon
    versions that switch their default representation.
    """
    if value in ("+", 1):
        return "+"
    if value in ("-", -1):
        return "-"
    return "0"
