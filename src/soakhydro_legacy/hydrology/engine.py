from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np

from ..models.common import AEP, DesignRainfall, Hyetograph, Project, TemporalPattern
from ..models.results import HydrographResult, RunoffEnsemble, SimulationReport
from .hyetograph import hyetograph_from_pattern
from .ilsax import simulate_catchment_runoff, summarise_hydrograph

Key = Tuple[AEP, int, int]


def design_rainfall_map(rainfalls: Iterable[DesignRainfall]) -> Dict[Tuple[AEP, int], DesignRainfall]:
    mapping: Dict[Tuple[AEP, int], DesignRainfall] = {}
    for item in rainfalls:
        mapping[(item.aep, item.duration_minutes)] = item
    return mapping


def get_timestep(duration_min):
    if duration_min <= 60:
        return max(1, duration_min // 6)
    elif duration_min <= 360:
        return 10
    elif duration_min <= 1440:
        return 30
    else:
        return 60


def generate_hyetographs(
    patterns: Mapping[Tuple[AEP, int], Sequence[TemporalPattern]],
    rainfalls: Mapping[Tuple[AEP, int], DesignRainfall],
) -> Dict[Key, Hyetograph]:
    import logging as _logging

    _log = _logging.getLogger(__name__)
    hyetographs: Dict[Key, Hyetograph] = {}
    for (aep, duration), pattern_list in patterns.items():
        design = rainfalls.get((aep, duration))
        if design is None:
            _log.warning(
                "No design rainfall for %s / %d min — skipping hyetograph generation for this combo",
                aep.to_label(),
                duration,
            )
            continue
        timestep_minutes = get_timestep(duration)
        for pattern in pattern_list:
            hyetographs[(aep, duration, pattern.pattern_rank)] = hyetograph_from_pattern(
                pattern, design, timestep_minutes
            )
    return hyetographs


def run_hydrology(
    project: Project,
    hyetographs: Mapping[Key, Hyetograph],
) -> SimulationReport:
    project.validate()
    runoff_results: Dict[Key, HydrographResult] = {}
    ensembles: Dict[Tuple[AEP, int], RunoffEnsemble] = {}
    hyeto_map: Dict[Key, Hyetograph] = dict(hyetographs)

    grouped: Dict[Tuple[AEP, int], list[HydrographResult]] = defaultdict(list)
    for key, hyeto in hyeto_map.items():
        aep, duration, pattern_rank = key
        total_discharge = None
        for catchment in project.catchments:
            discharge = np.array(simulate_catchment_runoff(catchment, hyeto))
            if total_discharge is None:
                total_discharge = discharge
            else:
                # Pad to equal length (time-area routing may extend the
                # hydrograph beyond the hyetograph duration)
                max_len = max(len(total_discharge), len(discharge))
                if len(total_discharge) < max_len:
                    total_discharge = np.pad(
                        total_discharge, (0, max_len - len(total_discharge))
                    )
                if len(discharge) < max_len:
                    discharge = np.pad(
                        discharge, (0, max_len - len(discharge))
                    )
                total_discharge += discharge
        if total_discharge is None:
            continue
        summary = summarise_hydrograph(aep, duration, pattern_rank, hyeto, total_discharge.tolist())
        runoff_results[key] = summary
        grouped[(aep, duration)].append(summary)

    for group_key, summaries in grouped.items():
        aep, duration = group_key
        ensembles[group_key] = RunoffEnsemble(
            aep=aep,
            duration_minutes=duration,
            results=sorted(summaries, key=lambda r: r.pattern_rank),
        )

    return SimulationReport(
        project_name=project.additional_metadata.get("project_name", "SoakSIM Project"),
        hyetographs=hyeto_map,
        runoff_results=runoff_results,
        ensembles=ensembles,
    )
