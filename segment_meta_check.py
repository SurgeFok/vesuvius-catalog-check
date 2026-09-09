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
import random
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
CATALOG_URL = BUCKET + "metadata.json"

# Identify the tool to whoever reads the bucket logs, so a burst of a few hundred GETs is
# attributable rather than anonymous.
USER_AGENT = "vesuvius-catalog-check (+https://github.com/SurgeFok/vesuvius-catalog-check)"

# A missing object is a finding about the data. A 5xx or a dropped connection is the
# network, and is worth retrying.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

# The canonical mesh artifact. The transformed/normalised/flattened variants are derived
# from it and repeat its defects, which would inflate every count several-fold.
ARTIFACT_TYPE = "tifxyz"


def _get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_with_retry(url, *, attempts=4, timeout=30, base_delay=0.5):
    """GET *url*, retrying transient failures with exponential backoff and jitter.

    Returns the body, or raises the last error. A 404 is not retried: the object is
    genuinely absent, which is a finding rather than a hiccup.
    """
    last = None
    for attempt in range(attempts):
        try:
            return _get(url, timeout)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in RETRYABLE_STATUS:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < attempts - 1:
            # Jitter so a pool of workers does not retry in lockstep.
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, base_delay))
    raise last


def load_catalog(source):
    if source.startswith(("http://", "https://")):
        raw = fetch_with_retry(source, timeout=120)
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


def fetch_all(targets, workers, cache_dir, *, delay=0.05, attempts=4):
    """Fetch every target, cache-first, politely.

    Concurrency is bounded and each worker pauses briefly between requests, so a sweep is
    a steady trickle against the bucket rather than a burst of a few hundred.
    """
    def one(target):
        sample, segment_id, scan_id, path = target
        cached = cache_dir / path.replace("/", "_") if cache_dir else None
        if cached and cached.exists():
            try:
                return sample, segment_id, scan_id, path, json.loads(cached.read_text())
            except json.JSONDecodeError:
                cached.unlink(missing_ok=True)  # a truncated cache entry is worse than none
        try:
            body = fetch_with_retry(BUCKET + path, attempts=attempts)
        except urllib.error.HTTPError as exc:
            return sample, segment_id, scan_id, path, {"__error__": f"HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001 - a missing mesh is a finding, not a crash
            return sample, segment_id, scan_id, path, {"__error__": type(exc).__name__}
        try:
            meta = json.loads(body)
        except json.JSONDecodeError:
            return sample, segment_id, scan_id, path, {"__error__": "invalid JSON"}
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(body)
        if delay:
            time.sleep(delay)
        return sample, segment_id, scan_id, path, meta

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
    parser.add_argument("--workers", type=int, default=8,
                        help="concurrent requests (default 8; the bucket is a courtesy)")
    parser.add_argument("--delay", type=float, default=0.05,
                        help="pause per worker between requests, in seconds")
    parser.add_argument("--attempts", type=int, default=4,
                        help="tries per request before giving up on a transient failure")
    parser.add_argument("--fail-on-finding", action="store_true")
    args = parser.parse_args()

    targets = list(mesh_targets(load_catalog(args.catalog)))
    if args.limit:
        targets = targets[: args.limit]
    print(f"Fetching {len(targets)} per-segment meta.json ...", file=sys.stderr)
    metas = fetch_all(targets, args.workers, args.cache_dir,
                      delay=args.delay, attempts=args.attempts)

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
