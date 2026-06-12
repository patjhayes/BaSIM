from __future__ import annotations

import traceback
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from ..hydraulics.optimizer import SoakwellDesignParameters
from ..models.common import AEP, Project
from ..pipeline import DataRepository, run_full_pipeline


class PipelineWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    started = Signal()

    def __init__(
        self,
        project: Project,
        params: SoakwellDesignParameters,
        aep: AEP,
        pattern_rank: int,
        use_live_data: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._params = params
        self._aep = aep
        self._pattern_rank = pattern_rank
        self._use_live_data = use_live_data

    @Slot()
    def run(self) -> None:
        self.started.emit()
        try:
            repo = DataRepository(use_live_data=self._use_live_data)
            report = run_full_pipeline(
                project=self._project,
                soakwell_params=self._params,
                data_repo=repo,
                aep_for_design=self._aep,
                pattern_rank=self._pattern_rank,
            )
        except Exception as exc:  # pragma: no cover - UI feedback path
            message = f"{exc}\n{traceback.format_exc()}"
            self.error.emit(message)
            return
        self.finished.emit(report)
