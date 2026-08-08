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

## Parity Verification

Canonical offline request and result fixtures are stored under
`tests/fixtures/gah_baseline`. They can be regenerated from a checkout of the
pinned source with:

```powershell
python scripts/capture_gah_baseline.py --gah-source <path-to-GAH-3D>
```

Run the migrated numerical and application parity suite with:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m pytest tests/engine -q
```