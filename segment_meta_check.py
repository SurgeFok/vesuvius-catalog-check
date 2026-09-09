#!/usr/bin/env python3
"""Checks over the per-segment `meta.json` files, which the catalog does not contain.

`metadata.json` describes the corpus; each published mesh carries its own small
`meta.json` alongside it holding `bbox`, `scale` and sometimes `area_vx2`. Several open
issues are defects in those rather than in the catalog, so they cannot be reached by
reading the catalog alone.

This is separate from the catalog checks because it makes one request per mesh -- a couple
of hundred small public GETs -- rather than the single fetch those need.

    python segment_meta_check.py                 # fetch and check
    python segment_meta_check.py --cache-dir m/  # keep the fetched files
    python segment_meta_check.py --limit 40      # sample instead of sweeping
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
CATALOG_URL = BUCKET + "metadata.json"

# The canonical mesh artifact. The transformed/normalised/flattened variants are derived
# from it and repeat its defects, which would inflate every count several-fold.
ARTIFACT_TYPE = "tifxyz"


def load_catalog(source):
    if source.startswith(("http://", "https://")):
        raw = urllib.request.urlopen(source, timeout=120).read()
    else:
        raw = open(source, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def mesh_targets(catalog):
    """(sample, segment_id, scan_id, meta.json path) for each canonical mesh."""
    for sample_name, sample in catalog.get("samples", {}).items():
        volumes = sample.get("volumes") or {}
        for segment_id, segment in (sample.get("segments") or {}).items():
            volume = volumes.get(segment.get("original_volume_id")) or {}
            scan_id = volume.get("scan_id")
            for artifact in segment.get("data") or []:
                if artifact.get("type") != ARTIFACT_TYPE:
                    continue
                for origin in artifact.get("origins") or []:
                    path = origin.get("path")
                    if path:
                        yield sample_name, segment_id, scan_id, path.rstrip("/") + "/meta.json"


def fetch_all(targets, workers, cache_dir):
    def one(target):
        sample, segment_id, scan_id, path = target
        cached = cache_dir / path.replace("/", "_") if cache_dir else None
        if cached and cached.exists():
            return sample, segment_id, scan_id, path, json.loads(cached.read_text())
        try:
            with urllib.request.urlopen(BUCKET + path, timeout=30) as response:
                body = response.read()
        except Exception as exc:  # noqa: BLE001 - a missing mesh is a finding, not a crash
            return sample, segment_id, scan_id, path, {"__error__": type(exc).__name__}
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(body)
        return sample, segment_id, scan_id, path, json.loads(body)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, targets))


def check_area_absent_by_scan(metas):
    """#1468: whole scans ship meshes with no `area_vx2` at all.

    Reported per scan rather than per mesh: one mesh missing the field is an omission, a
    scan where every mesh is missing it is a pipeline that never wrote it.
    """
    by_scan = defaultdict(lambda: [0, 0])
    for sample, _segment, scan, _path, meta in metas:
        if "__error__" in meta:
            continue
        counts = by_scan[f"{sample}/{scan}"]
        counts[0] += 1
        if "area_vx2" in meta:
            counts[1] += 1
    for scan, (total, present) in sorted(by_scan.items()):
        if total and present == 0:
            yield scan, f"area_vx2 absent from all {total} mesh(es)"


def check_bbox_inverted(metas):
    for sample, segment, _scan, _path, meta in metas:
        bbox = meta.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 2):
            continue
        lower, upper = bbox
        if not (isinstance(lower, list) and isinstance(upper, list)):
            continue
        axes = min(len(lower), len(upper))
        bad = [i for i in range(axes) if lower[i] > upper[i]]
        if bad:
            yield f"{sample}/{segment}", f"bbox axes {bad} have lower above upper"


def check_bbox_degenerate(metas):
    """A mesh occupying no volume on some axis."""
    for sample, segment, _scan, _path, meta in metas:
        bbox = meta.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 2):
            continue
        lower, upper = bbox
        if not (isinstance(lower, list) and isinstance(upper, list)):
            continue
        axes = min(len(lower), len(upper))
        flat = [i for i in range(axes) if lower[i] == upper[i]]
        if flat:
            yield f"{sample}/{segment}", f"bbox has zero extent on axes {flat}"


def check_scale_looks_like_a_grid_step(metas):
    """`scale` holding a grid step rather than a fraction.

    A tifxyz scale is a downsampling fraction, so it is at most 1; a value of ~20 is a grid
    step written into the wrong field.

    Not attributed to #1379. That issue is about `outer_shell/meta.json` under the
    spiral-input tree, and no artifact in the catalog points there -- the published types
    are obj, tifxyz and their variants, the zarr volumes, and the renders. So the invariant
    is kept as a guard over what is reachable, rather than claimed as a fix for that issue.
    """
    for sample, segment, _scan, _path, meta in metas:
        scale = meta.get("scale")
        values = scale if isinstance(scale, list) else [scale]
        offenders = [v for v in values if isinstance(v, (int, float)) and v > 1]
        if offenders:
            yield f"{sample}/{segment}", f"scale {offenders} exceeds 1"


def check_unfetchable(metas):
    for sample, segment, _scan, path, meta in metas:
        if "__error__" in meta:
            yield f"{sample}/{segment}", f"{meta['__error__']} fetching {path}"


CHECKS = {
    "area-absent-by-scan": (1468, check_area_absent_by_scan),
    "scale-is-a-grid-step": (None, check_scale_looks_like_a_grid_step),
    "bbox-inverted": (None, check_bbox_inverted),
    "bbox-degenerate": (None, check_bbox_degenerate),
    "meta-unfetchable": (None, check_unfetchable),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", default=CATALOG_URL)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="check only the first N")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--fail-on-finding", action="store_true")
    args = parser.parse_args()

    targets = list(mesh_targets(load_catalog(args.catalog)))
    if args.limit:
        targets = targets[: args.limit]
    print(f"Fetching {len(targets)} per-segment meta.json ...", file=sys.stderr)
    metas = fetch_all(targets, args.workers, args.cache_dir)

    total = 0
    print(f"Per-segment meta.json checks over {len(metas)} mesh(es)\n")
    for name, (issue, fn) in sorted(CHECKS.items()):
        findings = list(fn(metas))
        total += len(findings)
        label = f"#{issue}" if issue else "—"
        status = "ok  " if not findings else "FAIL"
        print(f"[{status}] {name:<22} {label:<7} {len(findings):>4}")
        for target, detail in findings[:10]:
            print(f"           {target}: {detail}")
        if len(findings) > 10:
            print(f"           ... {len(findings) - 10} more")
    print(f"\n{total} finding(s) across {len(CHECKS)} check(s)")
    return 1 if (total and args.fail_on_finding) else 0


if __name__ == "__main__":
    sys.exit(main())
