from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..models.catalogue import DEFAULT_SOAKWELL_CATALOGUE, SoakwellCatalogue, SoakwellSize
from ..models.results import HydrographResult, SoakwellDesign, SoakwellTimeSeries


@dataclass(slots=True)
class SoakwellDesignParameters:
    infiltration_rate_mm_per_hr: float
    design_drain_time_hours: float
    storage_safety_factor: float = 1.1
    infiltration_reduction_factor: float = 0.8
    allow_mixed_sizes: bool = False
    max_units: int = 50

    def validate(self) -> None:
        if self.infiltration_rate_mm_per_hr <= 0:
            raise ValueError("Infiltration rate must be positive")
        if self.design_drain_time_hours <= 0:
            raise ValueError("Drain time must be positive")
        if self.storage_safety_factor <= 0:
            raise ValueError("Storage safety factor must be positive")
        if not (0.0 < self.infiltration_reduction_factor <= 1.0):
            raise ValueError("Infiltration reduction factor must be within (0, 1]")
        if self.max_units <= 0:
            raise ValueError("Maximum number of units must be positive")


class SoakwellOptimizer:
    def __init__(self, catalogue: SoakwellCatalogue | None = None) -> None:
        self.catalogue = catalogue or DEFAULT_SOAKWELL_CATALOGUE

    # ── Helper methods ───────────────────────────────────────────────

    @staticmethod
    def _unit_storage(size: SoakwellSize) -> float:
        return size.storage_volume_m3

    @staticmethod
    def _unit_infiltration_rate_m3_per_hr(
        size: SoakwellSize, params: SoakwellDesignParameters
    ) -> float:
        """Infiltration volume per soakwell per hour (m³/hr)."""
        infiltration_rate_m_per_hr = params.infiltration_rate_mm_per_hr / 1000.0
        infiltration_area_m2 = size.side_area_m2 + size.base_area_m2
        return (
            infiltration_rate_m_per_hr
            * infiltration_area_m2
            * params.infiltration_reduction_factor
        )

    @staticmethod
    def _unit_infiltration(
        size: SoakwellSize, params: SoakwellDesignParameters
    ) -> float:
        """Total infiltration volume per unit over the design drain time (m³)."""
        return (
            SoakwellOptimizer._unit_infiltration_rate_m3_per_hr(size, params)
            * params.design_drain_time_hours
        )

    def route_through_soakwell(
        self,
        hydrograph: HydrographResult,
        design: SoakwellDesign,
        params: SoakwellDesignParameters,
        surface_ponding_factor: float = 50.0,
    ) -> SoakwellTimeSeries:
        """Route a hydrograph through the designed soakwell system.

        Uses a simple mass-balance at each time-step consistent with the
        Stormwater Management Manual for WA (Argue 2004):

          stored(t+1) = stored(t) + inflow − infiltration

        Concrete soakwells are hollow cylinders so void_ratio = 1.0 and
        storage = π/4 × d² × H per unit (no gravel reduction).

        Infiltration:
        - Base is always active when water is present.
        - Side-wall infiltration proportional to water depth / full height.
        - When spilling (water above the rim), all side walls are fully
          submerged → maximum infiltration rate.

        Spill / surface ponding:
        When accumulated water exceeds the soakwell capacity the soakwell
        spills.  Water ponds on the surface with a much larger plan area
        (surface_ponding_factor × total_base_area), so the depth barely
        increases above the rim.  The ponding area communicates freely
        with the soakwell so water drains back as the well empties.

        Parameters
        ----------
        surface_ponding_factor : float
            Ratio of surface ponding area to total soakwell base area.
            Default 50 — i.e. water spreads over ~50× the soakwell footprint.
        """
        # ── Aggregate properties across all soakwells ──
        total_storage_m3 = 0.0
        total_base_area_m2 = 0.0      # infiltration opening area (for infiltration calc)
        total_cross_section_m2 = 0.0   # full internal cross-section (for depth calc)
        total_side_area_m2 = 0.0
        weighted_height_sum = 0.0
        total_count = 0

        for name, count in design.configuration.items():
            size = self.catalogue.find(name)
            total_storage_m3 += count * size.storage_volume_m3
            total_base_area_m2 += count * size.base_area_m2
            total_cross_section_m2 += count * math.pi * size.radius_m ** 2
            total_side_area_m2 += count * size.side_area_m2
            weighted_height_sum += count * size.effective_height_m
            total_count += count

        avg_height_m = weighted_height_sum / max(total_count, 1)
        ponding_area_m2 = total_cross_section_m2 * surface_ponding_factor

        infil_rate_m_per_s = (
            params.infiltration_rate_mm_per_hr / 1000.0 / 3600.0
            * params.infiltration_reduction_factor
        )

        dt_s = hydrograph.timestep_minutes * 60.0
        n_storm = len(hydrograph.discharge_cms)
        # Run until soakwell drains to zero — safety cap at 10× drain time
        max_drain_steps = int(math.ceil(
            10.0 * params.design_drain_time_hours * 3600.0 / dt_s
        ))
        n_total = n_storm + max_drain_steps

        # Result lists
        time_min: list[float] = []
        cum_inflow: list[float] = []
        storage_vol: list[float] = []
        depth_list: list[float] = []
        cum_infil: list[float] = []
        cum_overflow: list[float] = []
        spill_flags: list[bool] = []

        acc_inflow = 0.0
        acc_infil = 0.0
        acc_overflow = 0.0
        stored = 0.0          # total retained water (can exceed soakwell capacity)

        for i in range(n_total):
            t = i * hydrograph.timestep_minutes

            # Inflow volume this step
            q_in = hydrograph.discharge_cms[i] if i < n_storm else 0.0
            inflow_vol = q_in * dt_s

            # ── Depth & spill state (before this step's inflow) ──
            if stored <= total_storage_m3:
                # Water is inside the soakwell(s)
                water_depth = stored / max(total_cross_section_m2, 1e-12)
                spilling = False
            else:
                # Soakwell full — excess is surface ponding
                excess = stored - total_storage_m3
                water_depth = avg_height_m + excess / max(ponding_area_m2, 1e-12)
                spilling = True

            depth_fraction = min(water_depth / avg_height_m, 1.0) if avg_height_m > 0 else 0.0

            # ── Infiltration ──
            # When spilling, all side walls are fully submerged → max area
            if spilling:
                active_infil_area = total_base_area_m2 + total_side_area_m2
            else:
                active_infil_area = total_base_area_m2 + total_side_area_m2 * depth_fraction

            max_infil_vol = infil_rate_m_per_s * active_infil_area * dt_s

            # Available water = stored + inflow
            available = stored + inflow_vol
            infil_vol = min(max_infil_vol, available)

            # Update storage (allow exceeding soakwell capacity = ponding)
            new_stored = available - infil_vol

            # Track overflow = cumulative volume that went above the rim
            if new_stored > total_storage_m3:
                overflow_this_step = max(0.0, (new_stored - total_storage_m3) - max(0.0, stored - total_storage_m3))
                acc_overflow += max(0.0, overflow_this_step + (inflow_vol - infil_vol) * 0) 
                # Simpler: track cumulative volume above rim
                acc_overflow = max(0.0, new_stored - total_storage_m3)

            stored = new_stored
            acc_inflow += inflow_vol
            acc_infil += infil_vol

            # ── Final depth after update ──
            if stored <= total_storage_m3:
                final_depth = stored / max(total_cross_section_m2, 1e-12)
                is_spilling = False
            else:
                excess = stored - total_storage_m3
                final_depth = avg_height_m + excess / max(ponding_area_m2, 1e-12)
                is_spilling = True

            time_min.append(round(t, 2))
            cum_inflow.append(round(acc_inflow, 6))
            storage_vol.append(round(stored, 6))
            depth_list.append(round(final_depth, 4))
            cum_infil.append(round(acc_infil, 6))
            cum_overflow.append(round(acc_overflow, 6))
            spill_flags.append(is_spilling)

            # Early termination: if drained and past the storm
            if i >= n_storm and stored < 1e-9:
                break

        return SoakwellTimeSeries(
            timestep_minutes=hydrograph.timestep_minutes,
            time_minutes=time_min,
            cumulative_inflow_m3=cum_inflow,
            storage_volume_m3=storage_vol,
            depth_m=depth_list,
            cumulative_infiltration_m3=cum_infil,
            spill_flag=spill_flags,
            cumulative_overflow_m3=cum_overflow,
        )
