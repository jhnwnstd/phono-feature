"""Portable logic for the New Inventory setup flow. Owns the
delimiter inference, validation rules, autofill seeds, and named
feature presets the desktop builder dialog and the web setup
modal share. Pure-Python; UI layers adapt to their native widgets.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from phonology_shared.data.limits import MAX_NAME_LENGTH
from phonology_shared.editor.phoible_features import PHOIBLE_TO_APP_FEATURE

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
# starting point for a custom set. The Hayes and PHOIBLE presets in
# the dropdown supply fuller starting points.
DEFAULT_FEATURES: str = "Syllabic\nConsonantal\n"

# Shared dialog strings (desktop dialog + web index.html both
# render the same setup modal).
SETUP_DIALOG_TITLE: str = "New inventory"
SETUP_NAME_PLACEHOLDER: str = "e.g. My Language Inventory"

# Feature-preset dropdown options. Insertion order = render order.
# Hayes mirrors hayes_features.json (pinned by test_setup_presets).
# PHOIBLE derives from PHOIBLE_TO_APP_FEATURE so bake refreshes flow.
FEATURE_PRESETS: Mapping[str, list[str]] = {
    "Hayes": [
        "CORONAL",
        "DORSAL",
        "LABIAL",
        "Anterior",
        "Approximant",
        "Back",
        "Consonantal",
        "ConstrGl",
        "Continuant",
        "DelRel",
        "Distributed",
        "Front",
        "High",
        "Labiodental",
        "Lateral",
        "Long",
        "Low",
        "Nasal",
        "Round",
        "Sonorant",
        "SpreadGl",
        "Stress",
        "Strident",
        "Syllabic",
        "Tap",
        "Tense",
        "Trill",
        "Voice",
    ],
    "PHOIBLE": list(PHOIBLE_TO_APP_FEATURE.values()),
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


def inventory_display_label(*, fname: str, metadata_name: str | None) -> str:
    """Return the dropdown label for an inventory file.

    Prefers a non-empty ``metadata.name`` from the JSON; falls back
    to the filename stem with the ``_features`` suffix stripped and
    underscores spaced. Both UIs delegate so the dropdown reads the
    same label whether produced at desktop runtime or at web build
    time.

    The web build precomputes this from each inventory's metadata
    block; the desktop reads the JSON header once per dropdown
    refresh.
    """
    if metadata_name is not None:
        cleaned = metadata_name.strip()
        if cleaned:
            return cleaned
    stem = fname[:-5] if fname.endswith(".json") else fname
    stem = stem.removesuffix("_features").replace("_", " ")
    return stem.title()


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


def _too_long(field: str, offender: str) -> str:
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
        issues.append(SetupIssue("segments", "empty", _MSG_NO_SEGMENTS))
    if not features:
        issues.append(SetupIssue("features", "empty", _MSG_NO_FEATURES))

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
                _too_long("segments", seg_offender),
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
                _too_long("features", feat_offender),
            )
        )

    return SetupResult(
        issues=tuple(issues),
        name=name,
        segments=tuple(segments),
        features=tuple(features),
    )
