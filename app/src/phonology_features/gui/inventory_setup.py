"""Portable logic for the New Inventory setup flow.

Shared by the desktop builder dialog (:py:mod:`phonology_features.gui.
builder.dialogs`) and the web app's setup modal (loaded via the build
relay into :py:mod:`api`). Nothing in this module imports Qt or
anything browser-specific. Every function is pure-Python; UI layers
adapt the results to their native widget vocabulary.

Single source of truth for:

* The delimiter inference rule that turns a textarea into a list.
* The validation rules that gate creation of a new inventory.
* The autofill / placeholder seed values shown when the user has
  not typed anything yet.
* The named feature presets the dropdown offers.

Edits to these definitions propagate to both UIs on the next build.
The previous structure had ``_infer_split`` and the ``DEFAULT_FILL``
strings buried inside Qt widget subclasses, which forced a parallel
re-implementation in the web. Extracting them keeps the two
frontends genuinely consistent rather than approximately consistent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from phonology_engine.limits import MAX_NAME_LENGTH

# Delimiters :py:func:`infer_split` tries, in no particular order.
# Whitespace is the FALLBACK (used only when none of these appear):
# feature names may legitimately contain spaces (for example "Long
# Vowel"), and the whole point of supporting explicit delimiters is
# to let those names survive paste.
EXPLICIT_DELIMITERS: tuple[str, ...] = (",", ";", "|", "\t", "\n")

# Tab-autofill seeds. Pure data so both the desktop QTextEdit
# subclasses and the web textarea reach for the same default.
#
# DEFAULT_SEGMENTS: IPA voiceless then voiced stops, with the
# trailing space so the caret lands ready for the next entry. The
# script-g (``ɡ``) is the legitimate IPA voiced velar stop, not
# ASCII g (segment-name folding in the inventory parser would
# normalize ASCII g to script-g anyway, but starting from canonical
# form keeps the placeholder display honest).
DEFAULT_SEGMENTS: str = "p b t d k ɡ "

# DEFAULT_FEATURES: the two major-class features as a minimal
# starting point for a custom set. The fuller "Default (33)" preset
# is available via the dropdown.
DEFAULT_FEATURES: str = "Syllabic\nConsonantal\n"

# Named feature presets. Keys are the dropdown labels, values are
# the feature lists. "Custom" is the no-fill option.
FEATURE_PRESETS: Mapping[str, list[str]] = {
    "Default (33)": [
        "Syllabic",
        "Consonantal",
        "Sonorant",
        "Approximant",
        "Voice",
        "SpreadGl",
        "ConstrGl",
        "Continuant",
        "Strident",
        "DelRel",
        "Nasal",
        "Lateral",
        "Trill",
        "Tap",
        "Click",
        "LABIAL",
        "Round",
        "Labiodental",
        "CORONAL",
        "Anterior",
        "Distributed",
        "DORSAL",
        "High",
        "Low",
        "Back",
        "Front",
        "Pharyngeal",
        "ATR",
        "Tense",
        "Long",
        "Stress",
        "Tone",
        "UpperRegister",
    ],
    "Custom": [],
}


def infer_split(text: str) -> list[str]:
    """Split ``text`` on whichever delimiter appears.

    Lets the user paste any consistently-delimited list (CSV, TSV,
    semicolons, pipes, one-per-line, plain whitespace) without
    pre-processing. The rule:

    * If any of ``,``, ``;``, ``|``, ``\\t``, ``\\n`` appears in the
      text, split on EVERY explicit delimiter that is present.
      Handles mixed cases like ``"p, b, t\\nd, e, f"`` (commas and
      newlines together) which should yield six tokens, not two
      strings of three.
    * Otherwise fall back to any-whitespace split (the legacy
      behaviour for ``"p b t d"``).

    Each token is whitespace-stripped; empties are filtered. Order
    is preserved.
    """
    used = [d for d in EXPLICIT_DELIMITERS if d in text]
    if not used:
        return [tok for tok in text.split() if tok]
    pattern = "|".join(re.escape(d) for d in used)
    return [tok.strip() for tok in re.split(pattern, text) if tok.strip()]


@dataclass(frozen=True)
class SetupIssue:
    """One validation problem with the inputs.

    ``field`` is ``"segments"``, ``"features"``, or ``"name"`` so a
    UI can route focus back to the offending widget. ``code`` is a
    stable identifier suitable for switching on; ``message`` is the
    human-readable explanation that already encodes the chosen
    error policy (mentions accepted delimiters, points at the cap).
    """

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class SetupResult:
    """Outcome of :py:func:`validate_setup`.

    ``issues`` is empty on success. ``name``, ``segments``, and
    ``features`` carry the parsed and trimmed values that should be
    handed to :py:meth:`Inventory.from_grid`.
    """

    issues: tuple[SetupIssue, ...]
    name: str
    segments: tuple[str, ...]
    features: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def suggest_filename(inv_name: str) -> str:
    """Slugify an inventory name into a bundled-style filename.

    Mirrors the bundled files (``hayes_features.json`` and
    similar): lowercase, non-alphanumeric runs collapsed to ``_``,
    ``_features`` suffix appended unless already present, ``.json``
    extension. Empty input falls back to ``untitled``.

    The desktop's Save As dialog uses this for the default
    filename. The web's download path uses it for the ``download``
    attribute so both frontends produce filenames that match the
    bundled inventories' naming convention.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", inv_name.lower()).strip("_")
    if not slug:
        slug = "untitled"
    if not slug.endswith("_features"):
        slug = f"{slug}_features"
    return f"{slug}.json"


def normalize_setup_name(raw: str) -> str:
    """Trim and default the inventory name.

    Mirrors the desktop's :py:meth:`InputDialog.get_name`: empty or
    whitespace-only falls back to ``"Untitled Inventory"``. The
    inventory parser would do the same fallback at parse time, but
    surfacing it here keeps the new-inventory contract honest about
    what gets stored.
    """
    stripped = raw.strip()
    return stripped if stripped else "Untitled Inventory"


# Static error messages. Lifted from the desktop dialog so the
# desktop and web surface identical wording. Each one names the
# accepted delimiters explicitly because the most common failure
# mode is "I pasted a wall of text with no recognized delimiter
# and got one giant entry".
_MSG_NO_SEGMENTS = (
    "The segments box is empty, or none of the recognized "
    "delimiters were found. Separate segments with any of: "
    "newline, space, tab, comma, semicolon, or pipe. "
    "Press Tab in an empty box for a quick-start set."
)
_MSG_NO_FEATURES = (
    "The features box is empty, or none of the recognized "
    "delimiters were found. Separate features with any of: "
    "newline, comma, semicolon, tab, or pipe. (Whitespace is "
    "allowed but only as a fallback, so feature names that "
    "contain spaces survive when you use a non-space delimiter.) "
    "Or pick a feature set from the dropdown."
)


def _too_long_message(field: str, offender: str) -> str:
    """Per-entry length-cap error message. Names the field, the
    offending length, and the cap, then explains the most common
    cause so the user knows where to look.
    """
    return (
        f"One of the {field} is {len(offender)} characters long, "
        f"longer than the {MAX_NAME_LENGTH}-character limit. This "
        f"usually means the delimiter was not recognized and the "
        f"whole input was treated as a single entry. Check the "
        f"delimiter and try again."
    )


def validate_setup(
    raw_name: str, segments_text: str, features_text: str
) -> SetupResult:
    """Validate the New Inventory inputs.

    The contract:

    * The inventory name is canonicalized via
      :py:func:`normalize_setup_name`; the empty case is allowed
      and produces ``"Untitled Inventory"``.
    * Segments and features text are split via
      :py:func:`infer_split`. An empty post-split list is an error.
    * Each entry must not exceed :py:data:`MAX_NAME_LENGTH`.

    Returns a :py:class:`SetupResult` with every problem found, not
    just the first. The caller decides whether to abort or which
    field to focus.
    """
    issues: list[SetupIssue] = []
    name = normalize_setup_name(raw_name)
    segments = infer_split(segments_text)
    features = infer_split(features_text)

    if not segments:
        issues.append(
            SetupIssue("segments", "empty", _MSG_NO_SEGMENTS)
        )
    if not features:
        issues.append(
            SetupIssue("features", "empty", _MSG_NO_FEATURES)
        )

    # Per-entry length cap. The desktop dialog short-circuits on the
    # first offender per field; we collect every offending field so
    # a UI that wants to surface all issues at once can.
    seg_offender = next(
        (e for e in segments if len(e) > MAX_NAME_LENGTH), None
    )
    if seg_offender is not None:
        issues.append(
            SetupIssue(
                "segments",
                "too_long",
                _too_long_message("segments", seg_offender),
            )
        )
    feat_offender = next(
        (e for e in features if len(e) > MAX_NAME_LENGTH), None
    )
    if feat_offender is not None:
        issues.append(
            SetupIssue(
                "features",
                "too_long",
                _too_long_message("features", feat_offender),
            )
        )

    return SetupResult(
        issues=tuple(issues),
        name=name,
        segments=tuple(segments),
        features=tuple(features),
    )
