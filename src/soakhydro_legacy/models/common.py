from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence


class AEP(Enum):
    """Annual exceedance probabilities supported by the application."""

    AEP_63_2 = 63.2
    AEP_50 = 50.0
    AEP_20 = 20.0
    AEP_10 = 10.0
    AEP_5 = 5.0
    AEP_2 = 2.0
    AEP_1 = 1.0

    @classmethod
    def from_percent(cls, value: float) -> "AEP":
        for member in cls:
            if abs(member.value - value) < 1e-6:
                return member
        raise ValueError(f"Unsupported AEP {value}")

    def to_label(self) -> str:
        return f"{self.value:g}%"


@dataclass(slots=True)
class Coordinate:
    latitude: float
    longitude: float

    def to_dict(self) -> Dict[str, float]:
        return {"latitude": self.latitude, "longitude": self.longitude}


@dataclass(slots=True)
class TemporalPattern:
    """Dimensionless infiltration pattern fractions for a given storm duration."""

    duration_minutes: int
    pattern_rank: int
    cumulative_fractions: Sequence[float]
    metadata: Dict[str, float | str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "duration_minutes": self.duration_minutes,
            "pattern_rank": self.pattern_rank,
            "cumulative_fractions": list(self.cumulative_fractions),
            "metadata": dict(self.metadata),
        }

    def validate(self) -> None:
        if not 1 <= self.pattern_rank <= 10:
            raise ValueError("Pattern rank must be between 1 and 10 inclusive")
        if len(self.cumulative_fractions) == 0:
            raise ValueError("Temporal pattern must have at least one fraction")
        if abs(self.cumulative_fractions[-1] - 1.0) > 1e-3:
            raise ValueError(
                "Temporal pattern cumulative fractions must finish at 1.0"
            )
        if any(x < 0 for x in self.cumulative_fractions):
            raise ValueError("Temporal pattern fractions must be non-negative")


@dataclass(slots=True)
class DesignRainfall:
    """Design rainfall depth/intensity for a given duration and AEP."""

    duration_minutes: int
    aep: AEP
    depth_mm: float
    intensity_mm_per_hr: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "duration_minutes": self.duration_minutes,
            "aep": self.aep.to_label(),
            "depth_mm": self.depth_mm,
            "intensity_mm_per_hr": self.intensity_mm_per_hr,
        }


@dataclass(slots=True)
class Hyetograph:
    """Rainfall time-series derived from temporal pattern + design rainfall."""

    timestep_minutes: float
    depths_mm: List[float]

    def total_depth(self) -> float:
        return sum(self.depths_mm)

    def peak_intensity_mm_per_hr(self) -> float:
        if not self.depths_mm:
            return 0.0
        dt_hr = self.timestep_minutes / 60.0
        return max(d / dt_hr for d in self.depths_mm)


@dataclass(slots=True)
class Catchment:
    """Catchment parameters for ILSAX runoff modelling (detailed mode).

    The ILSAX model divides each sub-catchment into three surface types:
      * **paved** – directly-connected impervious areas (DCIA)
      * **supplementary** – indirectly-connected impervious that drains
        across grassed areas before reaching the pipe system
      * **grassed** – pervious surfaces modelled with the Horton
        infiltration equation

    Soil type (1–4 ≡ A–D) and antecedent moisture condition (AMC 1–4)
    control the Horton curve used for the grassed component.

    Time-of-entry for each surface type is computed from the kinematic
    wave equation (Ragan & Duru Eq, Ragan & Duru 1972) using flow path
    length, slope and retardance coefficient n*, plus an additional
    (constant) time component:

        t_total = t_additional + 6.94·(L·n*)^0.6 / (I^0.4 · S^0.3)

    where L is in metres, S in m/m, I in mm/hr.
    """

    name: str
    area_ha: float
    slope: float

    # Surface-type fractions (must sum to 1.0)
    paved_fraction: float = 0.0
    supplementary_fraction: float = 0.0
    grassed_fraction: float = 0.0

    # Horton soil type: 1=A (sandy), 2=B, 3=C, 4=D (clay)
    soil_type: float = 2.0
    # Antecedent moisture condition: 1=dry … 4=saturated
    amc: float = 2.0

    # ── Detailed flow-path parameters per surface type ───────────────

    # Additional (constant) time component (minutes) — e.g. property drainage
    paved_additional_time_minutes: float = 0.0
    supplementary_additional_time_minutes: float = 0.0
    grassed_additional_time_minutes: float = 0.0

    # Flow path length (metres)
    paved_flow_path_length_m: float = 15.0
    supplementary_flow_path_length_m: float = 10.0
    grassed_flow_path_length_m: float = 20.0

    # Flow path slope (percent, e.g. 2.0 = 2%)
    paved_flow_path_slope_pct: float = 1.0
    supplementary_flow_path_slope_pct: float = 2.0
    grassed_flow_path_slope_pct: float = 2.0

    # Retardance coefficient n* (Table 8.3, Woolhiser 1975)
    # Typical: concrete/asphalt 0.011, bare soil 0.02, lawn 0.25
    paved_n_star: float = 0.011
    supplementary_n_star: float = 0.013
    grassed_n_star: float = 0.25

    # Depression storages (mm)
    paved_depression_storage_mm: float = 1.0
    supplementary_depression_storage_mm: float = 1.0
    grassed_depression_storage_mm: float = 5.0

    # ── derived helpers ──────────────────────────────────────────────

    def area_m2(self) -> float:
        return self.area_ha * 10_000

    @property
    def impervious_proportion(self) -> float:
        """Convenience: total impervious = paved + supplementary."""
        return self.paved_fraction + self.supplementary_fraction

    def validate(self) -> None:
        if self.area_ha <= 0:
            raise ValueError("Catchment area must be positive")
        if self.slope <= 0:
            raise ValueError("Catchment slope must be positive")
        total = self.paved_fraction + self.supplementary_fraction + self.grassed_fraction
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Surface fractions must sum to 1.0 (got {total:.3f})"
            )
        if any(f < 0 for f in (self.paved_fraction, self.supplementary_fraction, self.grassed_fraction)):
            raise ValueError("Surface fractions must be non-negative")
        if not (1.0 <= self.soil_type <= 4.0):
            raise ValueError("Soil type must be between 1 and 4")
        if not (1.0 <= self.amc <= 4.0):
            raise ValueError("AMC must be between 1 and 4")


@dataclass(slots=True)
class ProjectSettings:
    """Global simulation settings."""

    ae_ps: Sequence[AEP]
    durations_minutes: Sequence[int]

    def validate(self) -> None:
        if not self.ae_ps:
            raise ValueError("At least one AEP must be provided")
        if not self.durations_minutes:
            raise ValueError("At least one duration must be provided")


@dataclass(slots=True)
class Project:
    coordinate: Coordinate
    catchments: Sequence[Catchment]
    settings: ProjectSettings

    additional_metadata: Dict[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        self.settings.validate()
        for catchment in self.catchments:
            catchment.validate()

    def to_dict(self) -> Dict[str, object]:
        return {
            "coordinate": self.coordinate.to_dict(),
            "catchments": [c.__dict__ for c in self.catchments],
            "settings": {
                "ae_ps": [a.to_label() for a in self.settings.ae_ps],
                "durations_minutes": list(self.settings.durations_minutes),
            },
            "metadata": dict(self.additional_metadata),
        }
