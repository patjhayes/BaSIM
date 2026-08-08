"""End-to-end pipeline test using the bundled sample data.

This test would have caught the original config.default_project_settings() bug
(item 1) where a timestep_minutes kwarg was passed to a dataclass that lacks
that field, breaking `soaksim run-sample`.
"""

from __future__ import annotations

from soakhydro.models.common import AEP
from soakhydro.pipeline import create_sample_project, run_full_pipeline, DataRepository


def test_create_sample_project_builds_without_error():
    """create_sample_project() must not raise (regression guard for item 1)."""
    project = create_sample_project()
    assert project.coordinate is not None
    assert len(project.catchments) >= 1
    project.validate()


def test_run_full_pipeline_with_sample_data():
    """The full pipeline runs end-to-end with bundled sample ARR/BoM data and
    produces hyetographs and runoff results for the requested AEPs/durations."""
    project = create_sample_project()
    # Trim to a small AEP/duration set for a fast test.
    project.settings.ae_ps = (AEP.AEP_10, AEP.AEP_5)
    project.settings.durations_minutes = (30, 60)

    repo = DataRepository(use_live_data=False)
    report = run_full_pipeline(
        project=project,
        data_repo=repo,
        aep_for_design=AEP.AEP_5,
        pattern_rank=4,
    )

    assert report.project_name
    assert len(report.hyetographs) > 0, "Expected hyetographs to be generated"
    assert len(report.runoff_results) > 0, "Expected runoff results"
    assert len(report.ensembles) > 0, "Expected runoff ensembles"

    # Every runoff result should have a positive peak discharge and volume
    for res in report.runoff_results.values():
        assert res.peak_discharge_cms >= 0.0
        assert res.runoff_volume_m3 >= 0.0
        assert len(res.discharge_cms) > 0
