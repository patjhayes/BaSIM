from __future__ import annotations

from typing import Dict, Iterable, Tuple

from ..models.common import AEP
from ..models.results import HydrographResult, RunoffEnsemble


def rank_ensemble_by_peak(ensemble: RunoffEnsemble) -> Dict[int, HydrographResult]:
    """Rank hydrographs from highest to lowest peak discharge."""
    ranked = sorted(ensemble.results, key=lambda r: r.peak_discharge_cms, reverse=True)
    return {rank + 1: result for rank, result in enumerate(ranked)}


def select_pattern_by_rank(
    ensemble: RunoffEnsemble,
    desired_rank: int,
    conservative: bool = True,
) -> HydrographResult:
    ranking = rank_ensemble_by_peak(ensemble)
    if desired_rank in ranking:
        return ranking[desired_rank]
    if conservative:
        return ranking[min(ranking.keys())]
    return ranking[max(ranking.keys())]


def ensemble_statistics_table(ensembles: Iterable[RunoffEnsemble]) -> Dict[Tuple[AEP, int], Dict[str, float]]:
    table: Dict[Tuple[AEP, int], Dict[str, float]] = {}
    for ensemble in ensembles:
        table[(ensemble.aep, ensemble.duration_minutes)] = ensemble.statistics()
    return table
