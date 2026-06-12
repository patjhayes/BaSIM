from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .common import AEP, Hyetograph


@dataclass(slots=True)
class HydrographResult:
    """Stores runoff results for a single runoff simulation."""

    aep: AEP
    duration_minutes: int
    pattern_rank: int
    discharge_cms: Sequence[float]
    timestep_minutes: float
    peak_discharge_cms: float
    runoff_volume_m3: float
    time_to_peak_minutes: float


@dataclass(slots=True)
class RunoffEnsemble:
    """Collection of hydrograph results for all temporal patterns."""

    aep: AEP
    duration_minutes: int
    results: Sequence[HydrographResult]

    def ranked(self) -> List[HydrographResult]:
        return sorted(self.results, key=lambda r: r.peak_discharge_cms, reverse=True)

    def statistics(self) -> Dict[str, float]:
        peaks = [r.peak_discharge_cms for r in self.results]
        volumes = [r.runoff_volume_m3 for r in self.results]
        if not peaks:
            return {
                "max_peak_cms": 0.0,
                "median_peak_cms": 0.0,
                "mean_peak_cms": 0.0,
                "max_volume_m3": 0.0,
                "median_volume_m3": 0.0,
            }
        sorted_peaks = sorted(peaks)
        sorted_volumes = sorted(volumes)
        mid = len(peaks) // 2
        if len(peaks) % 2 == 1:
            median_peak = sorted_peaks[mid]
            median_volume = sorted_volumes[mid]
        else:
            median_peak = 0.5 * (sorted_peaks[mid - 1] + sorted_peaks[mid])
            median_volume = 0.5 * (sorted_volumes[mid - 1] + sorted_volumes[mid])
        return {
            "max_peak_cms": max(peaks),
            "median_peak_cms": median_peak,
            "mean_peak_cms": sum(peaks) / len(peaks),
            "max_volume_m3": max(volumes),
            "median_volume_m3": median_volume,
        }


@dataclass(slots=True)
class SoakwellDesign:
    aep: AEP
    critical_duration_minutes: int
    selected_pattern_rank: int
    required_storage_m3: float
    infiltration_shortfall_m3: float
    configuration: Dict[str, int]
    residual_storage_m3: float
    drain_time_hours: float
    notes: str = ""


@dataclass(slots=True)
class SoakwellTimeSeries:
    """Time-step results from routing a hydrograph through the soakwell system."""

    timestep_minutes: float
    time_minutes: List[float] = field(default_factory=list)
    cumulative_inflow_m3: List[float] = field(default_factory=list)
    storage_volume_m3: List[float] = field(default_factory=list)
    depth_m: List[float] = field(default_factory=list)
    cumulative_infiltration_m3: List[float] = field(default_factory=list)
    spill_flag: List[bool] = field(default_factory=list)
    cumulative_overflow_m3: List[float] = field(default_factory=list)


@dataclass(slots=True)
class SimulationReport:
    project_name: str
    hyetographs: Dict[tuple, Hyetograph] = field(default_factory=dict)
    runoff_results: Dict[tuple, HydrographResult] = field(default_factory=dict)
    ensembles: Dict[tuple, RunoffEnsemble] = field(default_factory=dict)
    soakwell_designs: Dict[AEP, SoakwellDesign] = field(default_factory=dict)
    soakwell_time_series: SoakwellTimeSeries | None = None
