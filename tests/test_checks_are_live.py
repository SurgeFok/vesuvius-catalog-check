"""Every check that currently passes is proven live by mutation.

Eight of the thirteen checks report nothing against today's catalog. A check that reports
nothing because it *cannot* report anything is worse than no check, since it reads as
assurance. Each one here is handed a catalog with a defect injected into the real published
data and must find it.

    python -m pytest tests/ -v

Needs a catalog snapshot; pass one with CATALOG=/path/to/metadata.json, otherwise
catalog-cache.json beside the checker is used, otherwise the live catalog is fetched.
"""

from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("checker", ROOT / "vesuvius_catalog_check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture(scope="session")
def catalog():
    source = os.environ.get("CATALOG")
    if not source:
        cache = ROOT / "catalog-cache.json"
        source = str(cache) if cache.exists() else checker.CATALOG_URL
    return checker.load_catalog(source)


def run(catalog, name):
    return list(checker.CHECKS[name](catalog))


def a_sample_with(catalog, kind):
    for name, sample in catalog["samples"].items():
        if sample.get(kind):
            return sample
    pytest.skip(f"no sample has any {kind}")


def assert_detects(catalog, name, mutate):
    """The check must find strictly more after the defect is injected."""
    before = len(run(catalog, name))
    mutated = copy.deepcopy(catalog)
    mutate(mutated)
    after = len(run(mutated, name))
    assert after > before, f"{name} did not detect the injected defect"


def test_volume_scan_dangling(catalog):
    def mutate(c):
        next(iter(a_sample_with(c, "volumes")["volumes"].values()))["scan_id"] = "NOPE"
    assert_detects(catalog, "volume-scan-dangling", mutate)


def test_segment_volume_dangling(catalog):
    def mutate(c):
        segment = next(iter(a_sample_with(c, "segments")["segments"].values()))
        segment["original_volume_id"] = "NOPE"
    assert_detects(catalog, "segment-volume-dangling", mutate)


def test_transform_target_dangling(catalog):
    def mutate(c):
        for sample in c["samples"].values():
            for volume in (sample.get("volumes") or {}).values():
                transforms = (volume.get("properties") or {}).get("transforms")
                if transforms:
                    transforms[0]["to_volume_id"] = "NOPE"
                    return
        pytest.skip("catalog declares no transforms")
    assert_detects(catalog, "transform-target-dangling", mutate)


def test_segment_dims_disagree(catalog):
    def mutate(c):
        segment = next(iter(a_sample_with(c, "segments")["segments"].values()))
        segment["properties"]["width"] = (segment["properties"].get("width") or 0) + 1
    assert_detects(catalog, "segment-dims-disagree", mutate)


def test_pixel_size_disagrees_with_scan(catalog):
    def mutate(c):
        volume = next(iter(a_sample_with(c, "volumes")["volumes"].values()))
        volume["properties"]["pixel_size_um"] = 999.0
    assert_detects(catalog, "pixel-size-disagrees-with-scan", mutate)


def test_data_format_mixed(catalog):
    def mutate(c):
        for sample in c["samples"].values():
            volumes = list((sample.get("volumes") or {}).values())
            if len(volumes) >= 2:
                volumes[0]["properties"]["data_format"] = "uint8"
                volumes[1]["properties"]["data_format"] = "uint16"
                return
        pytest.skip("no sample publishes two volumes")
    assert_detects(catalog, "data-format-mixed", mutate)


def test_coverage_bbox_inverted(catalog):
    def mutate(c):
        for sample in c["samples"].values():
            for segment in (sample.get("segments") or {}).values():
                coverage = (segment.get("properties") or {}).get("volume_coverage")
                if isinstance(coverage, dict) and coverage:
                    entry = next(iter(coverage.values()))
                    if isinstance(entry, dict) and entry.get("bbox_transformed"):
                        entry["bbox_transformed"] = [[9, 9, 9], [1, 1, 1]]
                        return
        pytest.skip("no segment carries a coverage bbox")
    assert_detects(catalog, "coverage-bbox-inverted", mutate)


def test_coverage_volume_dangling(catalog):
    def mutate(c):
        for sample in c["samples"].values():
            for segment in (sample.get("segments") or {}).values():
                coverage = (segment.get("properties") or {}).get("volume_coverage")
                if isinstance(coverage, dict) and coverage:
                    coverage["NOPE"] = next(iter(coverage.values()))
                    return
        pytest.skip("no segment carries volume_coverage")
    assert_detects(catalog, "coverage-volume-dangling", mutate)


def test_every_check_is_covered_here_or_fires_today(catalog):
    """No check may be silently unexercised: it either fires now or is mutation-tested."""
    mutation_tested = {
        name.removeprefix("test_").replace("_", "-")
        for name in globals()
        if name.startswith("test_") and name != "test_every_check_is_covered_here_or_fires_today"
    }
    unexercised = [
        name for name in checker.CHECKS
        if not run(catalog, name) and name not in mutation_tested
    ]
    assert not unexercised, f"checks neither firing nor mutation-tested: {unexercised}"
