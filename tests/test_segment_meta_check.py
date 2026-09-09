"""Checks over the per-segment meta.json files.

Fixtures are hand-built rather than fetched, so these run offline and pin the rules; the
network path is exercised by running segment_meta_check.py itself.
"""

from __future__ import annotations

import importlib.util
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
