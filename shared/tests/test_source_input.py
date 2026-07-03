"""Tests for the editor source-input normalizer."""

from __future__ import annotations

from phonology_shared.editor.source_input import normalize_source_input
from phonology_shared.presentation.source_link import classify_source


def test_plain_citation_passes_through_stripped():
    raw = "  Hayes, Bruce. 2009. Introductory Phonology. Wiley-Blackwell. "
    assert normalize_source_input(raw) == raw.strip()


def test_url_and_doi_pass_through_unchanged():
    assert (
        normalize_source_input("https://phoible.org/")
        == "https://phoible.org/"
    )
    assert normalize_source_input("10.1234/abc.def") == "10.1234/abc.def"
    # And they still classify as clickable links afterwards.
    assert (
        classify_source(normalize_source_input("https://x.org")).kind == "url"
    )
    assert classify_source(normalize_source_input("10.1000/xyz")).kind == "doi"


def test_empty_whitespace_and_none_yield_empty():
    assert normalize_source_input("") == ""
    assert normalize_source_input("   \n ") == ""
    assert normalize_source_input(None) == ""


def test_bibtex_book_renders_clean_citation():
    entry = """@book{hayes2009,
        author = {Hayes, Bruce},
        title  = {Introductory Phonology},
        year   = {2009},
        publisher = {Wiley-Blackwell}}"""
    assert (
        normalize_source_input(entry)
        == "Hayes, Bruce (2009). Introductory Phonology. Wiley-Blackwell."
    )
    # The rendered string is a plain citation for display.
    assert classify_source(normalize_source_input(entry)).kind == "citation"


def test_bibtex_article_multi_author_uses_journal():
    entry = (
        '@article{sd2020, author = "Smith, Jane and Doe, John", '
        'title = "A Study", journal = "Language", year = "2020"}'
    )
    assert (
        normalize_source_input(entry)
        == "Smith, Jane & Doe, John (2020). A Study. Language."
    )


def test_bibtex_three_authors_serial_comma_ampersand():
    entry = (
        "@article{k, author={A, X and B, Y and C, Z}, "
        "title={T}, year={2001}, journal={J}}"
    )
    assert normalize_source_input(entry).startswith(
        "A, X, B, Y & C, Z (2001)."
    )


def test_bibtex_nested_braces_in_title_stripped():
    entry = (
        "@incollection{x, author={Doe, J}, "
        "title={The {ATR} contrast}, year={2011}, booktitle={Handbook}}"
    )
    out = normalize_source_input(entry)
    assert "The ATR contrast" in out
    assert "{" not in out and "}" not in out


def test_bibtex_missing_fields_degrade_gracefully():
    entry = "@misc{x, title={Just a title}}"
    assert normalize_source_input(entry) == "Just a title."


def test_bibtex_no_usable_fields_falls_back_to_raw():
    entry = "@misc{x, note={nothing citational here}}"
    # note is not one of the rendered fields; keep the raw text rather
    # than emit an empty citation.
    assert normalize_source_input(entry) == entry.strip()


def test_bibtex_year_only():
    entry = "@book{x, year={1968}}"
    assert normalize_source_input(entry) == "(1968)."
