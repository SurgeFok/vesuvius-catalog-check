# vesuvius-catalog-check

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

## Proving the quiet checks are real

Eight of the thirteen report nothing against today's catalog. A check that reports nothing
because it *cannot* is worse than no check, since it reads as assurance. So each is handed
a copy of the real catalog with a defect injected — a dangling `scan_id`, a mismatched
`pixel_size_um`, an inverted bbox — and has to find it:

```
$ python -m pytest tests/ -q
9 passed
```

The ninth test is the one that keeps this honest: it fails if any check neither fires
against the live catalog nor appears in the mutation suite, so a new check cannot be added
without either finding something or proving it could.

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
