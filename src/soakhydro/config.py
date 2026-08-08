"""Global application configuration defaults."""

from __future__ import annotations

from .models.common import AEP, ProjectSettings

DEFAULT_AEPS = (
    AEP.AEP_63_2,
    AEP.AEP_50,
    AEP.AEP_20,
    AEP.AEP_10,
    AEP.AEP_5,
    AEP.AEP_2,
    AEP.AEP_1,
)

DEFAULT_DURATIONS_MIN = (
    6,
    12,
    18,
    24,
    30,
    45,
    60,
    90,
    120,
    180,
    270,
    360,
    540,
    720,
)

DEFAULT_TIME_STEP_MIN = 1.0


def default_project_settings() -> ProjectSettings:
    # NOTE: ProjectSettings has no timestep_minutes field — the per-storm
    # timestep is derived from duration in hydrology.engine.get_timestep().
    return ProjectSettings(
        ae_ps=DEFAULT_AEPS,
        durations_minutes=DEFAULT_DURATIONS_MIN,
    )
