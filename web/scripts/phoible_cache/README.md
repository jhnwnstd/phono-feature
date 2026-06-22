# Vendored PHOIBLE data

Two upstream PHOIBLE 2.0 files are vendored here, both gzipped to
keep the repository size sane:

- `phoible.csv.gz`: the phonological-inventory database. The raw
  CSV is 25 MB; gzipped it is under 1 MB at level 9, because the
  data is highly repetitive ``+`` / ``-`` / ``0`` columns that
  compress extremely well.
- `InventoryID-Bibtex.csv.gz`: the InventoryID to BibtexKey
  mapping. The main CSV omits each inventory's bibliographic
  source, so this is what lets a loaded inventory link to its
  phoible.org source page.

## Why vendored

`web/scripts/bake_phoible.py` runs on every web build to produce
two JSON snapshots under
``shared/src/phonology_shared/editor/`` that the PHOIBLE inventory
provider consumes. It reads both files above: the CSV for segment
data, and the mapping for each inventory's `source_page_url`.
Fetching these from GitHub on every CI build would add latency and
make the build fragile against network blips. PHOIBLE 2.0 was
released in April 2019 and updates rarely, so committing a snapshot
is the lower-risk choice.

## Source

- Upstream:
  - https://github.com/phoible/dev/blob/master/data/phoible.csv
  - https://github.com/phoible/dev/blob/master/mappings/InventoryID-Bibtex.csv
- Release: PHOIBLE 2.0
- Date: 2019-04-03
- License: GPL-3.0 (codebase) + CC BY-SA 3.0 (data)
- Citation: Moran, Steven & McCloy, Daniel (eds.) 2019. PHOIBLE 2.0.
  Jena: Max Planck Institute for the Science of Human History.
  Available online at http://phoible.org.
  DOI: 10.5281/zenodo.2626687

## Refreshing

If upstream publishes an update, refresh both files:

```sh
curl -sL https://raw.githubusercontent.com/phoible/dev/refs/heads/master/data/phoible.csv \
  | gzip -9 > web/scripts/phoible_cache/phoible.csv.gz

curl -sL https://raw.githubusercontent.com/phoible/dev/refs/heads/master/mappings/InventoryID-Bibtex.csv \
  | gzip -9 > web/scripts/phoible_cache/InventoryID-Bibtex.csv.gz
```

Then re-run ``python web/scripts/bake_phoible.py`` to regenerate
the JSON snapshots and verify tests still pass.
