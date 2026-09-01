# BaSIM Frontend

This is the vanilla multipage Vite port of the GAH-3D interface. It submits
design and clogging analyses to FastAPI, replays Redis-backed progress events,
polls durable job status, and retrieves completed results.

## Pages

- `index.html`: basin design and clogging analysis
- `billing.html`: project balances and Stripe checkout
- `help.html`: technical reference
- `login.html`: Supabase sign-in and account creation
- `product.html`: public product and project-pricing information
- `eula.html`: placeholder web-service EULA

## Setup

```powershell
npm ci
npm run dev
```

The dev server runs at `http://127.0.0.1:5174` and proxies `/api` to
`http://127.0.0.1:8000`. Set `VITE_API_URL`, `VITE_SUPABASE_URL`, and
`VITE_SUPABASE_ANON_KEY` for production builds.

Build all pages with `npm run build`.

Custom inflows are previewed through the authenticated multipart endpoint before
analysis submission. The backend accepts CSV and TS1 files only; configured
limits are 20 files, 5 MB per file, and 100,000 rows per file.
