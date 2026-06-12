from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .hydraulics.optimizer import SoakwellDesignParameters
from .pipeline import DataRepository, create_sample_project, run_full_pipeline
from .models.common import AEP
from .utils.paths import get_app_dir

app = typer.Typer(add_completion=False)
console = Console()
logging.basicConfig(level=logging.INFO)


@app.command()
def run_sample(
    use_live_data: bool = typer.Option(
        False,
        help="Fetch live ARR/BOM data instead of bundled samples",
    ),
    infiltration_rate: float = typer.Option(
        50.0,
        help="Soil infiltration rate in mm/hr",
    ),
    drain_time: float = typer.Option(
        24.0,
        help="Design drain-down time in hours",
    ),
    safety_factor: float = typer.Option(
        1.2,
        help="Storage safety factor",
    ),
    pattern_rank: int = typer.Option(
        1,
        min=1,
        max=10,
        help="Temporal pattern rank to design to (1=worst case)",
    ),
    aep_percent: float = typer.Option(
        5.0,
        help="AEP percentage to design the soakwell for",
    ),
    export_json: Optional[Path] = typer.Option(
        None,
        help="Optional path to export the simulation report as JSON",
    ),
    bom_json: Optional[Path] = typer.Option(
        None,
        help="Path to a BoM IFD JSON export to use for rainfall depths",
    ),
) -> None:
    """Run the full hydrology and soakwell design pipeline using sample inputs."""

    aep = AEP.from_percent(aep_percent)
    project = create_sample_project()

    params = SoakwellDesignParameters(
        infiltration_rate_mm_per_hr=infiltration_rate,
        design_drain_time_hours=drain_time,
        storage_safety_factor=safety_factor,
    )
    data_repo = DataRepository(use_live_data=use_live_data, bom_local_json=bom_json)

    report = run_full_pipeline(
        project=project,
        soakwell_params=params,
        data_repo=data_repo,
        aep_for_design=aep,
        pattern_rank=pattern_rank,
    )

    table = Table(title="SoakSIM Runoff Summary")
    table.add_column("AEP")
    table.add_column("Duration (min)")
    table.add_column("Pattern Rank")
    table.add_column("Peak Flow (m³/s)")
    table.add_column("Runoff Volume (m³)")

    for result in report.runoff_results.values():
        table.add_row(
            result.aep.to_label(),
            f"{result.duration_minutes}",
            f"{result.pattern_rank}",
            f"{result.peak_discharge_cms:.3f}",
            f"{result.runoff_volume_m3:.2f}",
        )

    console.print(table)

    design = report.soakwell_designs.get(aep)
    if design:
        console.print("\n[bold]Soakwell Design[/bold]")
        console.print(f"Critical duration: {design.critical_duration_minutes} min")
        console.print(f"Selected pattern rank: {design.selected_pattern_rank}")
        console.print(f"Required storage: {design.required_storage_m3:.2f} m³")
        console.print(f"Residual storage: {design.residual_storage_m3:.2f} m³")
        console.print(f"Infiltration shortfall: {design.infiltration_shortfall_m3:.2f} m³")
        console.print(f"Drain time: {design.drain_time_hours:.1f} h")
        console.print(f"Configuration: {design.configuration}")
    else:
        console.print("[yellow]No soakwell design recorded for selected AEP.[/yellow]")

    if export_json:
        export_json.parent.mkdir(parents=True, exist_ok=True)
        with export_json.open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "hyetographs": {
                        f"{a.value}_{duration}_{rank}": hyeto.depths_mm
                        for (a, duration, rank), hyeto in report.hyetographs.items()
                    },
                    "runoff_results": {
                        f"{res.aep.value}_{res.duration_minutes}_{res.pattern_rank}": {
                            "peak_discharge_cms": res.peak_discharge_cms,
                            "runoff_volume_m3": res.runoff_volume_m3,
                            "time_to_peak_minutes": res.time_to_peak_minutes,
                        }
                        for res in report.runoff_results.values()
                    },
                    "soakwell_designs": {
                        a.to_label(): {
                            "critical_duration_minutes": design.critical_duration_minutes,
                            "configuration": design.configuration,
                            "residual_storage_m3": design.residual_storage_m3,
                            "infiltration_shortfall_m3": design.infiltration_shortfall_m3,
                        }
                        for a, design in report.soakwell_designs.items()
                    },
                },
                fh,
                indent=2,
            )
        console.print(f"\nExported report to {export_json}")

    console.print(f"\nProject data stored in {get_app_dir()}")


if __name__ == "__main__":
    app()
