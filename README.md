# BaSIM v4

BaSIM is an authenticated stormwater infiltration-basin design application
using the Green-Ampt/Hantush 3D (GAH-3D) engine. It supports ARR/BoM rainfall
inputs, probability-neutral critical storm selection, groundwater mounding,
hydraulic outlet structures, and multi-year clogging degradation analysis.

## Architecture

BaSIM runs as four services:

1. A vanilla multipage Vite frontend.
2. A lightweight FastAPI backend for authentication, billing, validation, and
   durable job APIs.
3. A Celery compute worker that imports and runs the GAH-3D engine.
4. Redis as the Celery broker and the source of truth for job state, replayable
   progress events, cancellation flags, requests, and compressed results.

The API process does not import NumPy, SciPy, or the numerical engine. Jobs and
results expire after 24 hours by default. Reloading the frontend does not lose
job state because status and event history are persisted in Redis.

## Setup

Python 3.10 and Node 22 are the validated local versions.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

Set-Location frontend
npm ci
Set-Location ..

Copy-Item .env.example .env
```

Populate the Supabase, Stripe, and Vite values in `.env`. Apply
`database_schema.sql`, followed by `migrations/002_analysis_credits.sql` and
`migrations/003_billing_hardening.sql`, to the Supabase database. The migrations
supply atomic, idempotent analysis debit/refund and Stripe purchase functions.

## Run Locally

With Docker Compose:

```powershell
docker compose up
```

The frontend is available at `http://127.0.0.1:5174` and the API at
`http://127.0.0.1:8000`.

To run processes directly, start Redis and then use separate terminals:

```powershell
python -m uvicorn src.api.main:app --reload --port 8000
python -m celery -A src.worker.celery_app.celery_app worker --loglevel=info
Set-Location frontend; npm run dev
```

## Analysis API

All analysis and job routes require a Supabase bearer token.

- `POST /api/analyses/design`
- `POST /api/analyses/clogging`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/events?after=0`
- `GET /api/jobs/{job_id}/result`
- `POST /api/jobs/{job_id}/cancel`

Each design or clogging submission costs one credit for commercial accounts.
Addresses ending in `.gov.au` or `@innealta.com.au` use the free tier. Failed,
cancelled, or broker-rejected paid jobs use the idempotent refund function.

## Tests

Run the migrated engine and exact pinned-source parity suite:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m pytest tests/engine -q
```

Run API, Redis-store, worker-lifecycle, and billing/refund tests:

```powershell
python -m pytest tests/api tests/jobs tests/worker -q
```

Build the production frontend:

```powershell
Set-Location frontend
npm run build
```

Canonical offline design and clogging results are under
`tests/fixtures/gah_baseline`. See `VENDORED_GAH3D.md` for the pinned upstream
commit and fixture regeneration command.

## Deployment

`render.yaml` provisions the static frontend, FastAPI backend, Celery worker,
and Redis. Configure all `sync: false` environment variables in Render before
deployment and apply the database migrations first. Configure the Stripe
webhook endpoint as `/api/billing/webhook/stripe`, subscribe it to
`checkout.session.completed`, and set its signing secret as
`STRIPE_WEBHOOK_SECRET` on the backend service.

Live ARR/BoM access retains the vendored GAH cache and local fallback behavior.
A production-approved live feed or provisioned dataset remains a release gate
for engineering use.