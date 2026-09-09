"""No check may crash on a malformed catalog.

This tool exists to find malformed data, so dying on it is the one failure mode it cannot
have: a crash stops every other check from reporting, and the operator sees a traceback
instead of the twelve findings that were waiting behind it.

Each case is a shape the catalog could legitimately take -- an empty release, a key not yet
populated, a field present but null -- or one it takes when it is broken.
"""

from __future__ import annotations

import copy
import importlib.util
import json
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


def every_check(cat):
    """Run all checks, returning the names that raised."""
    broken = []
    for name, fn in checker.CHECKS.items():
        try:
            list(fn(cat))
        except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
            broken.append(f"{name}: {type(exc).__name__}: {exc}")
    return broken


@pytest.mark.parametrize("cat", [
    pytest.param({}, id="empty-object"),
    pytest.param({"models": {}}, id="samples-key-missing"),
    pytest.param({"samples": {}}, id="no-samples"),
    pytest.param({"samples": {"X": {"sample": "X"}}}, id="sample-with-no-collections"),
    pytest.param({"samples": {"X": {"volumes": None, "segments": None, "scans": None}}},
                 id="collections-null"),
])
def test_degenerate_catalogs_do_not_crash(cat):
    assert not every_check(cat)


def mutate_all(cat, kind, fn):
    out = copy.deepcopy(cat)
    for sample in out["samples"].values():
        for record in (sample.get(kind) or {}).values():
            fn(record)
    return out


def test_properties_present_but_null(catalog):
    """The #1516 family, taken one step further: the whole properties object is null."""
    assert not every_check(mutate_all(catalog, "volumes",
                                      lambda v: v.__setitem__("properties", None)))


def test_data_present_but_null(catalog):
    assert not every_check(mutate_all(catalog, "volumes",
                                      lambda v: v.__setitem__("data", None)))


def test_creation_present_but_null(catalog):
    assert not every_check(mutate_all(catalog, "segments",
                                      lambda s: s.__setitem__("creation", None)))


def test_shape_with_fewer_axes_than_the_bbox(catalog):
    """Indexing the shape by bbox axis crashed here."""
    assert not every_check(mutate_all(
        catalog, "volumes",
        lambda v: (v.get("properties") or {}).__setitem__("shape", [10]),
    ))


def test_coverage_is_the_wrong_type(catalog):
    assert not every_check(mutate_all(
        catalog, "segments",
        lambda s: s.__setitem__("properties", {"volume_coverage": []}),
    ))


def test_bbox_with_the_wrong_arity(catalog):
    def wreck(segment):
        coverage = (segment.get("properties") or {}).get("volume_coverage")
        if isinstance(coverage, dict):
            for key in coverage:
                coverage[key] = {"bbox_transformed": [[1, 2]], "overlap_ratio": 1.0}
    assert not every_check(mutate_all(catalog, "segments", wreck))


def test_unparseable_dates(catalog):
    assert not every_check(mutate_all(
        catalog, "volumes",
        lambda v: v.__setitem__("creation", {"date": "not-a-date"}),
    ))


def test_the_report_renders_for_a_degenerate_catalog(catalog):
    """A crash in reporting would hide the findings just as effectively."""
    results = checker.run({"samples": {}}, sorted(checker.CHECKS))
    checker.report_text({"samples": {}}, results, verbose=False)
    json.dumps([{"check": fn.check_name, "findings": f} for fn, f in results])
