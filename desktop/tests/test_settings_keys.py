"""Pins the :py:class:`SettingsKey` registry.

The enum centralises every QSettings key the app reads or writes;
the test guards against an editor accidentally renaming a member
(which would silently lose user settings on the next launch because
the new key would never match the existing stored value) or
removing a member without updating callers.

If you intentionally add or remove a key, update ``EXPECTED_KEYS``.
The set is the single registry the test owns.
"""

from __future__ import annotations

from phonology_features._settings import SettingsKey

# Every key the app currently reads or writes. The string values are
# what lives in the user's settings file; changing one of these
# silently orphans the previously-stored value, so the equality
# check below is strict.
EXPECTED_KEYS: dict[str, str] = {
    "WINDOW_POS": "window_pos",
    "WINDOW_SIZE": "window_size",
    "HSPLIT_STATE": "hsplit_state",
    "VSPLIT_STATE": "vsplit_state",
    "THEME": "theme",
    "PALETTE_MODE": "palette_mode",
    "MODE": "mode",
    "LAST_INVENTORY": "last_inventory",
    "MATCH_MODE": "match_mode",
}


def test_settings_key_registry_matches_expected() -> None:
    """Names and string values both match. A typo in the value
    (``"pallete_mode"``) or a rename of a member without updating
    ``EXPECTED_KEYS`` trips the test.
    """
    actual = {member.name: str(member) for member in SettingsKey}
    assert actual == EXPECTED_KEYS, (
        "SettingsKey registry drifted; if intentional update "
        "test_settings_keys.EXPECTED_KEYS"
    )


def test_settings_key_is_str_subclass() -> None:
    """``SettingsKey`` must be a :py:class:`StrEnum` so members can
    be passed directly to ``QSettings.setValue`` / ``settings.value``
    APIs that expect ``str`` keys, without an explicit ``str(...)``
    cast at every call site.
    """
    for member in SettingsKey:
        assert isinstance(member, str), (
            f"{member!r} is not a str subclass; SettingsKey must "
            "remain a StrEnum"
        )
