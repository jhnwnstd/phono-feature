"""Source-string classification for the unified [Source] affordance."""

from __future__ import annotations

from phonology_shared.presentation.source_link import (
    SourceLink,
    classify_source,
)


def test_http_url_is_a_link() -> None:
    link = classify_source("https://phoible.org/inventories/view/2")
    assert link.kind == "url"
    assert link.href == "https://phoible.org/inventories/view/2"


def test_bare_doi_resolves_through_doi_org() -> None:
    link = classify_source("10.5281/zenodo.2626687")
    assert link.kind == "doi"
    assert link.href == "https://doi.org/10.5281/zenodo.2626687"


def test_doi_prefix_is_stripped_for_the_href() -> None:
    link = classify_source("doi:10.5281/zenodo.2677911")
    assert link.kind == "doi"
    assert link.href == "https://doi.org/10.5281/zenodo.2677911"


def test_plain_text_is_a_citation_with_no_href() -> None:
    cite = "Hayes, Bruce (2009). Introductory Phonology. Wiley-Blackwell."
    link = classify_source(cite)
    assert link.kind == "citation"
    assert link.href == ""
    assert link.text == cite


def test_empty_or_none_is_no_source() -> None:
    assert classify_source("").kind == "none"
    assert classify_source(None).kind == "none"
    assert classify_source("   ").kind == "none"


def test_too_short_registrant_is_not_a_doi() -> None:
    # ``10.1/x`` has a one-digit registrant; not a well-formed DOI, so
    # it falls through to citation rather than minting a bogus link.
    assert classify_source("10.1/x").kind == "citation"


def test_non_string_source_is_coerced_not_crashed() -> None:
    # A hand-edited / future-baked inventory could carry a non-string
    # metadata.source; it must yield "none", never raise (a raise would
    # fail the whole inventory load on every frontend).
    for bad in ({"x": 1}, [1, 2], 123, 1.5, True):
        assert classify_source(bad).kind == "none"  # type: ignore[arg-type]


def test_dict_round_trip() -> None:
    link = classify_source("https://example.org")
    assert SourceLink.from_dict(link.as_dict()) == link
    assert SourceLink.from_dict(None).kind == "none"
