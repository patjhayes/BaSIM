from __future__ import annotations

import numpy as np

from ..models.common import DesignRainfall, Hyetograph, TemporalPattern


def hyetograph_from_pattern(
    pattern: TemporalPattern,
    design_rainfall: DesignRainfall,
    timestep_minutes: float,
) -> Hyetograph:
    """Generate a hyetograph using cumulative temporal pattern fractions."""

    if design_rainfall.duration_minutes != pattern.duration_minutes:
        raise ValueError("Pattern duration and design rainfall duration must match")

    fractions = np.asarray(pattern.cumulative_fractions, dtype=float)
    if fractions[-1] < 0.999:
        raise ValueError("Temporal pattern cumulative fractions must end at ~1.0")
    cumulative_depths = fractions * design_rainfall.depth_mm

    step_count = len(fractions)
    duration = design_rainfall.duration_minutes
    # Include zero at time zero for interpolation
    time_support = np.linspace(duration / step_count, duration, step_count)
    time_support = np.insert(time_support, 0, 0.0)
    cumulative_depths = np.insert(cumulative_depths, 0, 0.0)

    target_times = np.arange(timestep_minutes, duration + 1e-9, timestep_minutes)
    interpolated = np.interp(target_times, time_support, cumulative_depths)
    depths = np.diff(np.insert(interpolated, 0, 0.0))
    depths = depths.tolist()
    return Hyetograph(timestep_minutes=timestep_minutes, depths_mm=depths)
