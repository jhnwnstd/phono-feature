# Vendored Charis SIL font source

This directory holds the upstream Charis SIL font release we subset
into the IPA-only web font shipped at
[`web/assets/charis-ipa.woff2`](../../assets/charis-ipa.woff2).
The full release (~25 MB of TTFs across regular, bold, italic,
medium, semibold faces) is too large to track in git; only this
README stays committed so the refresh workflow is documented.

## Source

- Upstream: https://github.com/silnrsi/font-charis
- Release: Charis SIL 7.000
- License: SIL Open Font License (see
  [`web/assets/CHARIS_SIL_LICENSE.txt`](../../assets/CHARIS_SIL_LICENSE.txt))

## Refreshing the subset

If SIL publishes a new release and the app should pick up the
glyph updates, run the following from the repo root:

```sh
cd web/scripts/font_cache
curl -sL -o Charis-7.000.zip \
  'https://github.com/silnrsi/font-charis/releases/download/v7.000/Charis-7.000.zip'
unzip -q Charis-7.000.zip
cp Charis-7.000/OFL.txt ../../assets/CHARIS_SIL_LICENSE.txt
cd ../../..
python web/scripts/subset_ipa_font.py
```

The subset script writes the new `charis-ipa.woff2` directly under
`web/assets/`. Commit that file plus any license updates; leave
this `font_cache/` directory clean otherwise.
