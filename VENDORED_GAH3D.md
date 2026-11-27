# Vendored GAH-3D Source

BaSIM vendors the GAH-3D computational core from:

- Repository: `https://github.com/patjhayes/GAH-3D.git`
- Commit: `7258e44f47759ee23c9c73dba047698f7b40df6a`

## Included

- `src/soakhydro/hydraulics`
- `src/soakhydro/hydrology`
- `src/soakhydro/models`
- `src/soakhydro/services`
- `src/soakhydro/utils`
- `src/soakhydro/climate_change.py`
- `src/soakhydro/config.py`
- `src/soakhydro/pipeline.py`
- `sample_data`
- Computational regression tests under `tests/engine`

## Excluded

GAH-3D's FastAPI application, static UI, authentication, CLI, and desktop UI
were not vendored. BaSIM supplies those deployment and presentation layers.

The basin routing loop was extracted to
`src/soakhydro/hydraulics/routing.py`. Synchronous framework-neutral design
and clogging orchestration lives under `src/soakhydro/application`.

## Divergence From Pinned Source

`src/soakhydro/hydraulics/gah_3d_engine.py` (v1.3.1) corrects the Green-Ampt
ponding head to `Ks * (1 + (psi + h) * dtheta / F)`. The pinned commit used
`psi * dtheta + h`, which overstated the ponding-head contribution by a factor
of `1/dtheta`. The
fixtures under `tests/fixtures/gah_baseline` were regenerated from the BaSIM
engine, so they no longer match the pinned upstream output.
`scripts/capture_gah_baseline.py` reproduces the old behaviour when run
against the pinned upstream commit.

## Regression Verification

Canonical offline request and result fixtures are stored under
`tests/fixtures/gah_baseline`. The results reflect the BaSIM engine correction
described above and are regression baselines, not parity evidence for the
pinned source. Do not overwrite them with `scripts/capture_gah_baseline.py`
against the uncorrected pinned source.

Run the numerical and application regression suite with:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m pytest tests/engine -q
```