"""Checks over the per-segment meta.json files.

Fixtures are hand-built rather than fetched, so these run offline and pin the rules; the
network path is exercised by running segment_meta_check.py itself.
"""

from __future__ import annotations

import importlib.util

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("segmeta", ROOT / "segment_meta_check.py")
segmeta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(segmeta)


def meta(sample="S", segment="seg", scan="scan", **fields):
    return (sample, segment, scan, "p/meta.json", fields)


class TestAreaAbsentByScan:
    def test_a_scan_missing_it_everywhere_is_reported(self):
        metas = [meta(segment=f"s{i}", bbox=[[0, 0, 0], [1, 1, 1]]) for i in range(3)]
        found = list(segmeta.check_area_absent_by_scan(metas))
        assert len(found) == 1
        assert "all 3 mesh(es)" in found[0][1]

    def test_one_mesh_carrying_it_clears_the_scan(self):
        """An omission on a single mesh is not a pipeline that never wrote the field."""
        metas = [meta(segment="a"), meta(segment="b", area_vx2=12.0)]
        assert not list(segmeta.check_area_absent_by_scan(metas))

    def test_scans_are_judged_separately(self):
        metas = [meta(scan="x", area_vx2=1.0), meta(scan="y")]
        found = list(segmeta.check_area_absent_by_scan(metas))
        assert len(found) == 1 and found[0][0] == "S/y"

    def test_unfetchable_metas_do_not_count_as_missing(self):
        metas = [meta(segment="a", area_vx2=1.0), meta(segment="b", __error__="HTTPError")]
        assert not list(segmeta.check_area_absent_by_scan(metas))


class TestBbox:
    def test_inverted_axis_is_reported(self):
        found = list(segmeta.check_bbox_inverted([meta(bbox=[[5, 0, 0], [1, 9, 9]])]))
        assert found and "[0]" in found[0][1]

    def test_a_sane_bbox_passes(self):
        assert not list(segmeta.check_bbox_inverted([meta(bbox=[[0, 0, 0], [1, 1, 1]])]))

    def test_zero_extent_is_reported(self):
        found = list(segmeta.check_bbox_degenerate([meta(bbox=[[0, 3, 0], [1, 3, 1]])]))
        assert found and "[1]" in found[0][1]

    def test_missing_or_malformed_bbox_is_skipped_not_crashed(self):
        for bad in (None, [], [[0, 0, 0]], "nope", [[0, 0], "x"]):
            assert not list(segmeta.check_bbox_inverted([meta(bbox=bad)]))
            assert not list(segmeta.check_bbox_degenerate([meta(bbox=bad)]))


class TestScale:
    def test_a_grid_step_in_the_scale_field_is_reported(self):
        found = list(segmeta.check_scale_looks_like_a_grid_step([meta(scale=[20.0, 20.0])]))
        assert found and "20.0" in found[0][1]

    def test_a_downsampling_fraction_passes(self):
        assert not list(segmeta.check_scale_looks_like_a_grid_step([meta(scale=[0.05, 0.05])]))

    def test_a_scalar_scale_is_handled(self):
        assert list(segmeta.check_scale_looks_like_a_grid_step([meta(scale=7)]))
        assert not list(segmeta.check_scale_looks_like_a_grid_step([meta(scale=1)]))

    def test_missing_scale_is_skipped(self):
        assert not list(segmeta.check_scale_looks_like_a_grid_step([meta()]))


class TestUnfetchable:
    def test_a_failed_fetch_is_a_finding(self):
        found = list(segmeta.check_unfetchable([meta(__error__="HTTPError")]))
        assert found and "HTTPError" in found[0][1]


class TestTargets:
    def test_only_the_canonical_mesh_type_is_taken(self):
        """The transformed and flattened variants repeat the same defects."""
        catalog = {"samples": {"S": {
            "volumes": {"v1": {"scan_id": "sc1"}},
            "segments": {"g1": {"original_volume_id": "v1", "data": [
                {"type": "tifxyz", "origins": [{"path": "a/"}]},
                {"type": "tifxyz-transformed", "origins": [{"path": "b/"}]},
                {"type": "obj", "origins": [{"path": "c/"}]},
            ]}},
        }}}
        targets = list(segmeta.mesh_targets(catalog))
        assert targets == [("S", "g1", "sc1", "a/meta.json")]

    def test_a_segment_without_a_published_volume_still_yields(self):
        catalog = {"samples": {"S": {"segments": {"g": {
            "original_volume_id": "missing",
            "data": [{"type": "tifxyz", "origins": [{"path": "a/"}]}],
        }}}}}
        assert list(segmeta.mesh_targets(catalog)) == [("S", "g", None, "a/meta.json")]


class TestFetchWithRetry:
    """Retry code that is never exercised is where hangs and silent give-ups live."""

    def _patch(self, monkeypatch, responses):
        """Feed _get a scripted sequence; each entry is a body or an exception."""
        calls = {"n": 0}

        def fake_get(url, timeout):
            index = calls["n"]
            calls["n"] += 1
            outcome = responses[min(index, len(responses) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(segmeta, "_get", fake_get)
        monkeypatch.setattr(segmeta.time, "sleep", lambda _s: None)
        return calls

    def test_a_first_time_success_does_not_retry(self, monkeypatch):
        calls = self._patch(monkeypatch, [b"ok"])
        assert segmeta.fetch_with_retry("u") == b"ok"
        assert calls["n"] == 1

    def test_a_transient_failure_is_retried_then_succeeds(self, monkeypatch):
        import urllib.error
        calls = self._patch(monkeypatch, [
            urllib.error.URLError("connection reset"), b"ok",
        ])
        assert segmeta.fetch_with_retry("u") == b"ok"
        assert calls["n"] == 2

    def test_a_retryable_status_is_retried(self, monkeypatch):
        import urllib.error
        calls = self._patch(monkeypatch, [
            urllib.error.HTTPError("u", 503, "slow down", {}, None), b"ok",
        ])
        assert segmeta.fetch_with_retry("u") == b"ok"
        assert calls["n"] == 2

    def test_a_404_is_not_retried(self, monkeypatch):
        """The object is genuinely absent; retrying only pesters the bucket."""
        import urllib.error
        calls = self._patch(monkeypatch, [
            urllib.error.HTTPError("u", 404, "not found", {}, None),
        ])
        with pytest.raises(urllib.error.HTTPError):
            segmeta.fetch_with_retry("u")
        assert calls["n"] == 1

    def test_it_gives_up_after_the_attempt_budget(self, monkeypatch):
        import urllib.error
        calls = self._patch(monkeypatch, [urllib.error.URLError("down")])
        with pytest.raises(urllib.error.URLError):
            segmeta.fetch_with_retry("u", attempts=3)
        assert calls["n"] == 3

    def test_the_request_identifies_the_tool(self, monkeypatch):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["ua"] = request.get_header("User-agent")

            class R:
                def read(self): return b"{}"
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R()

        monkeypatch.setattr(segmeta.urllib.request, "urlopen", fake_urlopen)
        segmeta._get("https://example.invalid/x", 5)
        assert "vesuvius-catalog-check" in seen["ua"]


class TestFetchAllRobustness:
    def test_a_corrupt_cache_entry_is_discarded_not_returned(self, monkeypatch, tmp_path):
        (tmp_path / "a_meta.json").write_text("{not json")
        monkeypatch.setattr(segmeta, "fetch_with_retry", lambda *a, **k: b'{"scale": [0.1]}')
        result = segmeta.fetch_all([("S", "g", "sc", "a/meta.json")], 1, tmp_path, delay=0)
        assert result[0][4] == {"scale": [0.1]}

    def test_invalid_json_from_the_bucket_is_a_finding(self, monkeypatch):
        monkeypatch.setattr(segmeta, "fetch_with_retry", lambda *a, **k: b"<html>")
        result = segmeta.fetch_all([("S", "g", "sc", "a/meta.json")], 1, None, delay=0)
        assert result[0][4]["__error__"] == "invalid JSON"

    def test_an_http_error_records_its_status(self, monkeypatch):
        import urllib.error

        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 403, "denied", {}, None)

        monkeypatch.setattr(segmeta, "fetch_with_retry", boom)
        result = segmeta.fetch_all([("S", "g", "sc", "a/meta.json")], 1, None, delay=0)
        assert result[0][4]["__error__"] == "HTTP 403"
