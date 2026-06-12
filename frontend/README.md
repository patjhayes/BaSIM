# BasinSIM Frontend (Vue 3 + Vite)

This is the modern BasinSIM UI. It talks to the FastAPI backend on http://localhost:8000.

## Prerequisites (Windows)
- Install Node.js LTS from https://nodejs.org (includes npm)

## Setup
1. Open a terminal in this folder.
2. Install deps: `npm install`
3. Run dev server: `npm run dev`
4. Open http://localhost:5173

Backend: from the repo root, run the backend with:
- `python -m uvicorn src.api.main:app --reload --port 8000`

TailwindCSS is configured via `tailwind.config.js`; styles are in `src/styles.css` and imported by `src/main.ts`.
