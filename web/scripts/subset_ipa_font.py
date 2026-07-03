#!/usr/bin/env python3
"""Subset Charis SIL Regular to the IPA-relevant Unicode ranges.

The web app cannot ship a full ~880 KB TTF to every visitor when
the only glyphs we actually render are Latin Basic plus IPA
extensions plus combining diacritical marks. Subsetting to those
ranges and converting to WOFF2 brings the asset to roughly 150
to 200 KB before gzip, small enough that the browser caches it
on first paint and combining marks render identically across
platforms instead of inheriting whatever the system monospace
fallback decides.

Run standalone:
    python web/scripts/subset_ipa_font.py [--out PATH]

The script is idempotent. The vendored source font lives under
``web/scripts/font_cache/Charis-7.000/`` (gitignored, refreshed
manually). The subset output lives at
``web/assets/charis-ipa.woff2`` and is committed so the build
pipeline does not need fonttools at deploy time.

Source: Charis SIL 7.000 from SIL International, distributed under
the Open Font License. See ``CHARIS_OFL.txt`` next to the source
TTF for the full license text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
SOURCE_TTF = (
    WEB_DIR / "scripts" / "font_cache" / "Charis-7.000" / "Charis-Regular.ttf"
)
DEFAULT_OUT = WEB_DIR / "assets" / "charis-ipa.woff2"

# Unicode ranges we keep. Each tuple is ``(start, end)`` inclusive.
# Covers what the app actually renders: ASCII, Latin Extended for
# accented Latin letters in language names, the IPA Extensions
# block, the Spacing Modifier Letters block (for ejective glyphs
# and length marks), Combining Diacritical Marks (the tilde,
# below-ring, etc. that PHOIBLE attaches to base segments),
# Phonetic Extensions and Supplement, and General Punctuation.
KEEP_RANGES: tuple[tuple[int, int], ...] = (
    (0x0020, 0x007E),  # Basic Latin
    (0x00A0, 0x024F),  # Latin-1 Supplement + Latin Extended-A/B
    (0x0250, 0x02AF),  # IPA Extensions
    (0x02B0, 0x02FF),  # Spacing Modifier Letters
    (0x0300, 0x036F),  # Combining Diacritical Marks
    (0x1D00, 0x1D7F),  # Phonetic Extensions
    (0x1D80, 0x1DBF),  # Phonetic Extensions Supplement
    (0x1DC0, 0x1DFF),  # Combining Diacritical Marks Supplement
    (0x2000, 0x206F),  # General Punctuation
    (0xA700, 0xA71F),  # Modifier Tone Letters
)

REQUIRED_CODEPOINTS = frozenset(
    {
        ord("a"),
        ord("ɡ"),
        ord("ʃ"),
        ord("ː"),
        ord("\u0303"),  # Combining tilde
        ord("\u0325"),  # Combining ring below
    }
)


def _format_unicode_ranges(ranges: tuple[tuple[int, int], ...]) -> str:
    """Render the ranges as the CSS ``unicode-range`` token string."""
    parts: list[str] = []
    for lo, hi in ranges:
        if lo == hi:
            parts.append(f"U+{lo:04X}")
        else:
            parts.append(f"U+{lo:04X}-{hi:04X}")
    return ", ".join(parts)


def _validate_ranges(ranges: tuple[tuple[int, int], ...]) -> None:
    """Fail fast if a hand-maintained Unicode range is invalid."""
    previous_hi = -1
    for lo, hi in ranges:
        if lo > hi:
            raise ValueError(f"invalid Unicode range: U+{lo:04X}-U+{hi:04X}")
        if lo <= previous_hi:
            raise ValueError(
                f"overlapping or unsorted Unicode range at U+{lo:04X}"
            )
        previous_hi = hi


def _codepoints_for_ranges(ranges: tuple[tuple[int, int], ...]) -> list[int]:
    """Expand inclusive Unicode ranges into codepoints for fonttools."""
    _validate_ranges(ranges)
    return [codepoint for lo, hi in ranges for codepoint in range(lo, hi + 1)]


def _assert_required_codepoints(font: object) -> None:
    """Verify that representative IPA-critical glyphs survived subsetting."""
    cmap = set(font.getBestCmap())
    missing = REQUIRED_CODEPOINTS - cmap
    if missing:
        formatted = ", ".join(f"U+{cp:04X}" for cp in sorted(missing))
        raise RuntimeError(
            f"subset font is missing required glyphs: {formatted}"
        )


def subset_font(source: Path, out: Path) -> None:
    """Subset ``source`` to the IPA ranges and write WOFF2 to ``out``.

    Uses fonttools' high-level Subsetter so we can express the
    ranges declaratively instead of poking at the lower-level TTF
    tables. Brotli is required for WOFF2 output and ships via the
    ``fonttools[woff]`` extra.
    """
    try:
        from fontTools.subset import Options, Subsetter
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError(
            "fonttools not installed; run "
            "`pip install 'fonttools[woff]' brotli` first"
        ) from exc

    if not source.exists():
        raise FileNotFoundError(
            f"source TTF not found at {source}; "
            "extract Charis-7.000.zip into web/scripts/font_cache/ first"
        )

    font = TTFont(str(source))
    options = Options()
    options.flavor = "woff2"
    # Drop hinting tables; modern WOFF2 viewers ignore them and we
    # save ~10% on output size by stripping them at subset time.
    options.hinting = False
    options.desubroutinize = True
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.legacy_kern = False
    # Keep OpenType features that PHOIBLE-related glyphs depend on:
    # kerning for combining-mark placement, mark positioning. Drop
    # contextual-alternate and discretionary-ligature paths since
    # the seg-btn CSS disables them in ``font-feature-settings``.
    options.layout_features = [
        "kern",
        "mark",
        "mkmk",
        "ccmp",
        "abvm",
        "blwm",
        "locl",
        "rlig",
    ]

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=_codepoints_for_ranges(KEEP_RANGES))
    subsetter.subset(font)
    _assert_required_codepoints(font)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(out.suffix + ".tmp")
    try:
        font.flavor = "woff2"
        font.save(str(tmp_out))
        tmp_out.replace(out)
    finally:
        if tmp_out.exists():
            tmp_out.unlink()

    if out.stat().st_size == 0:
        raise RuntimeError(f"font subset wrote an empty file to {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_TTF,
        help=f"Path to Charis-Regular.ttf (default: {SOURCE_TTF})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output WOFF2 path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args()

    try:
        subset_font(args.source, args.out)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"subset_ipa_font: {exc}\n")
        return 1

    kb = args.out.stat().st_size / 1024
    print(
        f"subset_ipa_font: wrote {kb:.1f} KB WOFF2 to {args.out}\n"
        f"  unicode-range = {_format_unicode_ranges(KEEP_RANGES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
