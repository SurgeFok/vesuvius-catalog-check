# vesuvius-catalog-check

[![tests](https://github.com/SurgeFok/vesuvius-catalog-check/actions/workflows/tests.yml/badge.svg)](https://github.com/SurgeFok/vesuvius-catalog-check/actions/workflows/tests.yml)

A consistency checker for the [Vesuvius Challenge](https://scrollprize.org) published
data catalog.

The whole corpus — 45 samples, 67 scans, 71 volumes, 311 segments — is described by a
single public `metadata.json`. Everything downstream trusts it: `vesuvius` resolves
volumes through it, tooling reads shapes and voxel sizes from it, and provenance is
expressed as `derived_from` pointers between its records. When a field is null or a
pointer dangles, the failure surfaces much later and much less legibly.

This runs thirteen structural checks over that catalog in well under a second, with no
credentials and nothing to build.

## Usage

```
python3 vesuvius_catalog_check.py                      # fetch and check the live catalog
python3 vesuvius_catalog_check.py --list-checks
python3 vesuvius_catalog_check.py --check volume-shape-null --verbose
python3 vesuvius_catalog_check.py --json                # machine-readable
python3 vesuvius_catalog_check.py --fail-on-finding     # exit 1 on any finding, for CI
```

Standard library only, Python 3.9+. `--source` accepts a local path so a snapshot can be
checked offline; gzip is detected automatically.

## Checks

| Check | Issue | What it looks for |
|---|---|---|
| `volume-shape-null` | [#1516](https://github.com/ScrollPrize/villa/issues/1516) | `properties.shape` is null although the level-0 `.zarray` has it |
| `derived-from-dangling` | [#1504](https://github.com/ScrollPrize/villa/issues/1504) | `creation.derived_from` id does not resolve as its declared type |
| `segment-predates-source` | [#1730](https://github.com/ScrollPrize/villa/issues/1730) | segment is older than the scan its source volume came from |
| `creation-info-inconsistent` | [#1436](https://github.com/ScrollPrize/villa/issues/1436) | an artifact deviates from its type's `creation_info` convention |
| `coverage-ratio-contradicts-bbox` | [#1734](https://github.com/ScrollPrize/villa/issues/1734) | `overlap_ratio` is 1.0 while the bbox falls outside the volume |
| `coverage-volume-dangling` | — | `volume_coverage` keyed by a volume the sample does not publish |
| `coverage-bbox-inverted` | — | bbox lower corner above its upper corner |
| `data-format-mixed` | — | one sample publishes volumes in mixed integer widths |
| `pixel-size-disagrees-with-scan` | [#1381](https://github.com/ScrollPrize/villa/issues/1381) | volume `pixel_size_um` differs from its scan |
| `segment-volume-dangling` | [#1649](https://github.com/ScrollPrize/villa/issues/1649) | `original_volume_id` is not a published volume |
| `volume-scan-dangling` | — | `scan_id` does not resolve within the sample |
| `transform-target-dangling` | — | `transforms[].to_volume_id` is not published |
| `segment-dims-disagree` | — | `properties` width/height disagree with `creation.metadata` |

Checks that currently pass are kept deliberately: they are regressions worth catching,
and a check that passes today is evidence the catalog is clean in that dimension.

## Mutation tests

Eight of the thirteen checks report nothing against today's catalog. Reporting nothing
because the check is broken looks identical to reporting nothing because the data is clean,
so each of the eight is handed a copy of the real catalog with one defect injected — a
dangling `scan_id`, a `pixel_size_um` that disagrees with its scan, an inverted bbox — and
has to find it.

```
$ python -m pytest tests/ -q
9 passed
```

A ninth test fails if any check neither fires against the live catalog nor appears in the
mutation suite. Adding a check therefore requires it to find something, or to be shown that
it could.

## Malformed catalogs

A validator that dies on bad input is the one failure mode this tool cannot have: the
traceback replaces every finding that was queued behind it. So the checks are also run over
catalogs that are empty, missing their `samples` key, carrying `properties: null` rather
than an absent key, holding a bbox with more axes than the volume's shape, or dating a
record `"not-a-date"`.

Two of those crashed the coverage check when the suite was first written — `properties`
present but null, and a shape with fewer axes than the bbox. Both were the exact
malformation the tool is meant to report.

## Per-segment meta.json

`metadata.json` describes the corpus, but each published mesh carries its own small
`meta.json` holding `bbox`, `scale` and sometimes `area_vx2`. Some open issues are defects
in those, so they cannot be reached by reading the catalog at all.

[`segment_meta_check.py`](segment_meta_check.py) covers them. It is separate because it
makes one request per mesh — 188 small public GETs — rather than the single fetch the
catalog checks need.

```
python segment_meta_check.py                 # fetch and check
python segment_meta_check.py --cache-dir m/  # keep what it fetched
python segment_meta_check.py --limit 40      # sample rather than sweep
```

It reads only the canonical `tifxyz` artifact. The transformed, normalised and flattened
variants are derived from it and repeat its defects, which would multiply every count.

### [#1468](https://github.com/ScrollPrize/villa/issues/1468) reproduces, with different numbers

```
Per-segment meta.json checks over 188 mesh(es)

[FAIL] area-absent-by-scan    #1468      5
           PHerc0172/20241024131838: area_vx2 absent from all 1 mesh(es)
           PHerc0332/20231117143551: area_vx2 absent from all 2 mesh(es)
           PHerc0343P/20250510090703: area_vx2 absent from all 8 mesh(es)
           PHerc0500P2/20250507210011: area_vx2 absent from all 39 mesh(es)
           PHercParis4/20230205180739: area_vx2 absent from all 11 mesh(es)
[ok  ] bbox-degenerate        —          0
[ok  ] bbox-inverted          —          0
[ok  ] meta-unfetchable       —          0
[ok  ] scale-is-a-grid-step   —          0

5 finding(s) across 5 check(s)
```

The issue reports `area_vx2` absent from two scans covering 73 of 185 meshes. Against
today's data it is five scans covering 61 of 188. Reported per scan rather than per mesh:
one mesh missing the field is an omission, a scan where every mesh is missing it is a
pipeline that never wrote it.

`scale-is-a-grid-step` is deliberately not attributed to
[#1379](https://github.com/ScrollPrize/villa/issues/1379). That issue concerns
`outer_shell/meta.json` under the spiral-input tree, and no artifact in the catalog points
there — the published types are `obj`, `tifxyz` and their variants, the zarr volumes and
the renders. The invariant is kept as a guard over what is reachable.

## Findings

See [FINDINGS.md](FINDINGS.md) for the current run against the live catalog.

## One check deliberately not written

`bbox_transformed` sits outside its volume's extent in 981 places. That is not reported as
a defect: the bbox has been pushed through a transform and which frame it lands in is
exactly the open question in
[#1734](https://github.com/ScrollPrize/villa/issues/1734), so those 981 may be a frame
convention rather than an error. What is reported instead is the subset that contradicts
itself — 407 records claiming `overlap_ratio` of 1.0 while placing their own bbox outside
the volume they name. That holds whichever frame is meant.

`data-format-mixed` is likewise not attributed to #1654: that issue concerns the
`instance-labels-harmonized` label volumes, which this catalog does not describe. The
invariant is kept as a generic guard rather than claimed as a fix.

## Why the counts are calibrated

Three checks reproduce their upstream issue's reported count exactly, which is the
evidence that they measure the right thing:

- `volume-shape-null` finds **4**; #1516 reports four volumes.
- `derived-from-dangling` finds **3**, all `PHerc0009B`, all typed `volume` but resolving
  only as `scan`; #1504 reports exactly that.
- `segment-predates-source` finds **20**; #1730 reports 20 segments.

Two checks were wrong on the first pass and are worth naming, because both failure modes
are easy to ship by accident:

- `segment-predates-source` originally compared the segment against its source *volume*
  date and found 47. #1730 compares against the *scan*. On the correct basis it is 20.
- `creation-info-inconsistent` originally flagged every null `creation_info` and found
  396. But null is the convention for whole artifact types — `ome-zarr` is 71/71 null,
  `tifxyz-flattened` 122/122 — so most of that was noise. It now reports only the
  minority side of a lopsided split, which is 29 and includes the Lasagna artifact #1436
  describes, plus three more the issue does not mention.

## License

MIT
