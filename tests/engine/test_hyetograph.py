from soakhydro.hydrology.hyetograph import hyetograph_from_pattern
from soakhydro.models.common import DesignRainfall, TemporalPattern, AEP


def test_hyetograph_total_depth_matches_design():
    pattern = TemporalPattern(
        duration_minutes=60,
        pattern_rank=1,
        cumulative_fractions=[0.2, 0.5, 0.8, 1.0],
    )
    pattern.validate()
    design = DesignRainfall(
        duration_minutes=60,
        aep=AEP.AEP_5,
        depth_mm=60.0,
        intensity_mm_per_hr=60.0,
    )
    hyeto = hyetograph_from_pattern(pattern, design, timestep_minutes=15)

    assert abs(sum(hyeto.depths_mm) - design.depth_mm) < 1e-6
    assert len(hyeto.depths_mm) == 4
    assert hyeto.peak_intensity_mm_per_hr() >= 0
