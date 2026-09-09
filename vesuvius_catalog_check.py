#!/usr/bin/env python3
"""Consistency checker for the Vesuvius Challenge published data catalog.

Reads the public `metadata.json` catalog and reports structural defects:
dangling references, null required fields, cross-record disagreements and
impossible provenance ordering.

Each check names the upstream issue it evidences, so a report can be pasted
directly into that issue.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime

CATALOG_URL = "https://vesuvius-challenge-open-data.s3.amazonaws.com/metadata.json"

CHECKS = {}


def check(name, issue, summary):
    def register(fn):
        fn.check_name = name
        fn.issue = issue
        fn.summary = summary
        CHECKS[name] = fn
        return fn

    return register


def load_catalog(source):
    if source.startswith(("http://", "https://")):
        raw = urllib.request.urlopen(source, timeout=120).read()
    else:
        raw = open(source, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def parse_date(value):
    """Catalog dates are ISO-8601 with a trailing Z, occasionally fractional."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def records(catalog, kind):
    """Yield (sample_name, record_id, record) for every record of a kind."""
    for sample_name, sample in catalog.get("samples", {}).items():
        for record_id, record in (sample.get(kind) or {}).items():
            yield sample_name, record_id, record


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

@check("volume-shape-null", 1516,
       "volumes publish properties.shape: null despite a level-0 .zarray shape")
def volume_shape_null(catalog):
    for sample, vid, volume in records(catalog, "volumes"):
        if (volume.get("properties") or {}).get("shape") is None:
            yield f"{sample}/{vid}", "properties.shape is null"


@check("volume-scan-dangling", None,
       "volume.scan_id does not resolve to a scan in the same sample")
def volume_scan_dangling(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        scans = set((sample.get("scans") or {}).keys())
        for vid, volume in (sample.get("volumes") or {}).items():
            scan_id = volume.get("scan_id")
            if scan_id and scan_id not in scans:
                yield f"{sample_name}/{vid}", f"scan_id {scan_id} not in sample"


@check("derived-from-dangling", 1504,
       "creation.derived_from points at an id that does not resolve to its declared type")
def derived_from_dangling(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        pools = {kind: set((sample.get(kind) or {}).keys())
                 for kind in ("scans", "volumes", "segments")}
        for kind in ("scans", "volumes", "segments"):
            for rid, record in (sample.get(kind) or {}).items():
                src = (record.get("creation") or {}).get("derived_from")
                if not src or not src.get("id"):
                    continue
                declared = src.get("type")
                pool = pools.get(f"{declared}s", set())
                if src["id"] in pool:
                    continue
                found = [k for k, ids in pools.items() if src["id"] in ids]
                detail = f"declared type '{declared}', id {src['id']}"
                detail += f" resolves only as {found[0][:-1]}" if found else " resolves to nothing"
                yield f"{sample_name}/{kind[:-1]}/{rid}", detail


@check("segment-volume-dangling", 1649,
       "segment.original_volume_id is not a volume published for that sample")
def segment_volume_dangling(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = set((sample.get("volumes") or {}).keys())
        for sid, segment in (sample.get("segments") or {}).items():
            vid = segment.get("original_volume_id")
            if vid and vid not in volumes:
                yield f"{sample_name}/{sid}", f"original_volume_id {vid} not published"


@check("transform-target-dangling", None,
       "properties.transforms[].to_volume_id does not resolve to a published volume")
def transform_target_dangling(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = set((sample.get("volumes") or {}).keys())
        for vid, volume in (sample.get("volumes") or {}).items():
            for transform in (volume.get("properties") or {}).get("transforms") or []:
                target = transform.get("to_volume_id")
                if target and target not in volumes:
                    yield f"{sample_name}/{vid}", f"transform target {target} not published"


@check("segment-predates-source", 1730,
       "segment is dated before the scan its source volume was reconstructed from")
def segment_predates_source(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = sample.get("volumes") or {}
        scans = sample.get("scans") or {}
        for sid, segment in (sample.get("segments") or {}).items():
            volume = volumes.get(segment.get("original_volume_id"))
            if not volume:
                continue
            scan = scans.get(volume.get("scan_id"))
            if not scan:
                continue
            seg_date = parse_date((segment.get("creation") or {}).get("date"))
            scan_date = parse_date((scan.get("creation") or {}).get("date"))
            if seg_date and scan_date and seg_date < scan_date:
                gap = (scan_date - seg_date).days
                yield (f"{sample_name}/{sid}",
                       f"scan {scan['id']} is {gap} days newer than the segment")


@check("segment-dims-disagree", None,
       "properties.width/height disagree with creation.metadata width/height")
def segment_dims_disagree(catalog):
    for sample, sid, segment in records(catalog, "segments"):
        props = segment.get("properties") or {}
        meta = (segment.get("creation") or {}).get("metadata") or {}
        for field in ("width", "height"):
            declared, recorded = props.get(field), meta.get(field)
            if declared is not None and recorded is not None and declared != recorded:
                yield f"{sample}/{sid}", f"{field}: properties={declared} creation={recorded}"


@check("pixel-size-disagrees-with-scan", 1381,
       "volume pixel_size_um differs from the scan it was derived from")
def pixel_size_disagrees(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        scans = sample.get("scans") or {}
        for vid, volume in (sample.get("volumes") or {}).items():
            scan = scans.get(volume.get("scan_id"))
            if not scan:
                continue
            vol_px = (volume.get("properties") or {}).get("pixel_size_um")
            scan_px = (scan.get("properties") or {}).get("pixel_size_um")
            if vol_px and scan_px and abs(vol_px - scan_px) > 1e-9:
                drift = abs(vol_px - scan_px) / scan_px * 100
                yield f"{sample_name}/{vid}", f"volume {vol_px} vs scan {scan_px} ({drift:.2f}% drift)"


@check("data-format-mixed", None,
       "a sample publishes volumes in mixed integer widths")
def data_format_mixed(catalog):
    """Generic guard, not #1654.

    #1654 is about the `instance-labels-harmonized` label volumes, which this catalog does
    not describe, so it is not claimed here. The invariant is still worth holding: a
    consumer that reads one volume of a sample and sizes buffers from its dtype should not
    be surprised by the next.
    """
    for sample_name, sample in catalog.get("samples", {}).items():
        by_format = defaultdict(list)
        for vid, volume in (sample.get("volumes") or {}).items():
            fmt = (volume.get("properties") or {}).get("data_format")
            if fmt:
                by_format[fmt].append(vid)
        if len(by_format) > 1:
            spread = ", ".join(f"{fmt}x{len(ids)}" for fmt, ids in sorted(by_format.items()))
            yield sample_name, f"mixed data_format across volumes: {spread}"


@check("creation-info-inconsistent", 1436,
       "an artifact deviates from its type's creation_info convention")
def creation_info_inconsistent(catalog, minority_ceiling=0.25):
    """Each artifact type either carries creation_info or does not.

    A type split overwhelmingly one way has a convention, and the handful of
    records on the other side are the defect -- that is the shape of #1436,
    where one Lasagna artifact lacks the field its siblings all have.
    A type split near the middle is unsettled, not broken, so it is not
    reported.
    """
    with_info = defaultdict(list)
    without_info = defaultdict(list)
    for kind in ("volumes", "segments"):
        for sample, rid, record in records(catalog, kind):
            for artifact in record.get("data") or []:
                target = f"{sample}/{kind[:-1]}/{rid}"
                bucket = without_info if artifact.get("creation_info") is None else with_info
                bucket[artifact.get("type")].append(target)

    for artifact_type in sorted(set(with_info) | set(without_info)):
        present, absent = with_info[artifact_type], without_info[artifact_type]
        total = len(present) + len(absent)
        if not present or not absent:
            continue  # a consistent convention either way
        deviating, verb = (absent, "missing") if len(absent) < len(present) else (present, "carrying")
        if len(deviating) / total > minority_ceiling:
            continue  # the type is genuinely split; nothing to call out
        for target in deviating:
            yield target, (f"type '{artifact_type}' is the only {len(deviating)}/{total} "
                           f"{verb} creation_info")


@check("coverage-volume-dangling", None,
       "volume_coverage is keyed by a volume the sample does not publish")
def coverage_volume_dangling(catalog):
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = set((sample.get("volumes") or {}).keys())
        for sid, segment in (sample.get("segments") or {}).items():
            coverage = (segment.get("properties") or {}).get("volume_coverage")
            if not isinstance(coverage, dict):
                continue
            for volume_id in coverage:
                if volume_id not in volumes:
                    yield f"{sample_name}/{sid}", f"coverage key {volume_id} not published"


@check("coverage-bbox-inverted", None,
       "volume_coverage bbox has a lower corner above its upper corner")
def coverage_bbox_inverted(catalog):
    for sample, sid, segment in records(catalog, "segments"):
        coverage = (segment.get("properties") or {}).get("volume_coverage")
        if not isinstance(coverage, dict):
            continue
        for volume_id, entry in coverage.items():
            bbox = (entry or {}).get("bbox_transformed")
            if not (isinstance(bbox, list) and len(bbox) == 2):
                continue
            lower, upper = bbox
            bad = [i for i, (lo, hi) in enumerate(zip(lower, upper)) if lo > hi]
            if bad:
                yield f"{sample}/{sid}", f"volume {volume_id}: axes {bad} inverted"


@check("coverage-ratio-contradicts-bbox", 1734,
       "overlap_ratio claims full coverage while the bbox falls outside the volume")
def coverage_ratio_contradicts_bbox(catalog):
    """An internal contradiction between two fields of the same record.

    The raw question "is bbox_transformed inside the volume?" is deliberately NOT asked:
    the bbox has been pushed through a transform and which frame it lands in is exactly
    what #1734 is about, so 981 apparent violations there may be a frame convention rather
    than a defect. But a record claiming overlap_ratio 1.0 while placing its own bbox
    outside the volume it names disagrees with itself whichever frame is meant, and that
    holds without resolving #1734.
    """
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = sample.get("volumes") or {}
        for sid, segment in (sample.get("segments") or {}).items():
            coverage = (segment.get("properties") or {}).get("volume_coverage")
            if not isinstance(coverage, dict):
                continue
            for volume_id, entry in coverage.items():
                entry = entry or {}
                if entry.get("overlap_ratio") != 1.0:
                    continue
                volume = volumes.get(volume_id)
                shape = (volume or {}).get("properties", {}).get("shape")
                bbox = entry.get("bbox_transformed")
                if not shape or not (isinstance(bbox, list) and len(bbox) == 2):
                    continue  # #1516 volumes have no shape to check against
                lower, upper = bbox
                outside = [
                    i for i, (lo, hi) in enumerate(zip(lower, upper))
                    if lo < 0 or hi > shape[i]
                ]
                if outside:
                    yield (f"{sample_name}/{sid}",
                           f"volume {volume_id}: overlap_ratio 1.0 but axes {outside} "
                           f"fall outside shape {shape}")


# --------------------------------------------------------------------------

def run(catalog, selected):
    results = []
    for name in selected:
        fn = CHECKS[name]
        results.append((fn, list(fn(catalog))))
    return results


def report_text(catalog, results, verbose):
    samples = catalog.get("samples", {})
    counts = {k: sum(len(s.get(k) or {}) for s in samples.values())
              for k in ("scans", "volumes", "segments")}
    print("Vesuvius catalog check")
    print(f"  {len(samples)} samples · " + " · ".join(f"{v} {k}" for k, v in counts.items()))
    print()
    total = 0
    for fn, findings in results:
        total += len(findings)
        issue = f"#{fn.issue}" if fn.issue else "—"
        status = "ok  " if not findings else "FAIL"
        print(f"[{status}] {fn.check_name:<28} {issue:<7} {len(findings):>4}  {fn.summary}")
        limit = len(findings) if verbose else 8
        for target, detail in findings[:limit]:
            print(f"           {target}: {detail}")
        if len(findings) > limit:
            print(f"           ... {len(findings) - limit} more (use --verbose)")
    print()
    print(f"{total} finding(s) across {len(results)} check(s)")
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=CATALOG_URL,
                        help="catalog URL or local path (gzip detected automatically)")
    parser.add_argument("--check", action="append", metavar="NAME",
                        help="run only this check (repeatable)")
    parser.add_argument("--list-checks", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--verbose", action="store_true", help="list every finding")
    parser.add_argument("--fail-on-finding", action="store_true",
                        help="exit 1 when any check reports a finding")
    args = parser.parse_args()

    if args.list_checks:
        for name, fn in sorted(CHECKS.items()):
            issue = f"#{fn.issue}" if fn.issue else "—"
            print(f"{name:<28} {issue:<7} {fn.summary}")
        return 0

    selected = args.check or sorted(CHECKS)
    unknown = [n for n in selected if n not in CHECKS]
    if unknown:
        parser.error(f"unknown check(s): {', '.join(unknown)}")

    catalog = load_catalog(args.source)
    results = run(catalog, selected)

    if args.json:
        payload = [{"check": fn.check_name, "issue": fn.issue, "summary": fn.summary,
                    "findings": [{"target": t, "detail": d} for t, d in f]}
                   for fn, f in results]
        json.dump(payload, sys.stdout, indent=2)
        print()
        total = sum(len(f) for _, f in results)
    else:
        total = report_text(catalog, results, args.verbose)

    return 1 if (total and args.fail_on_finding) else 0


if __name__ == "__main__":
    sys.exit(main())
