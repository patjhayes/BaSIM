Grid sensitivity tools
======================

- grid_sensitivity.py: run a sweep of min cell sizes and record runtime and peak-stage deltas.

Quick start (from VS Code Run/Debug):
- Run the module src/dev/grid_sensitivity.py. It will generate outputs under model_output/analysis/grid_sensitivity/.

Programmatic example:

from src.dev.grid_sensitivity import run_grid_sweep, SweepSpec

cfg = { 'scenario_title': 'My Scenario', 'basin_geometry': {...}, 'aquifer': {...}, 'infiltration': {...} }
run_grid_sweep(ts1_path=r"DRAINS/OUTPUT/my.ts1", base_config=cfg, sweep=SweepSpec(min_cell_sizes=(0.5,1,2,3,5)))
