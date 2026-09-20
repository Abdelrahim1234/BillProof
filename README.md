# BillBuster

BillBuster turns an itemized hospital bill into a source-backed review. It compares
each usable billing code with the hospital's own published prices, explains what
is and is not comparable, and creates a practical call packet without claiming
that a charge is illegal or incorrect.

The hackathon demo uses a clearly labeled synthetic patient bill and verified,
non-synthetic public price rows from:

- LewisGale Hospital Montgomery
- Carilion New River Valley Medical Center

No multi-gigabyte hospital machine-readable files are committed to this repo.
The checked-in seed is a small, provenance-rich extract of the rows needed for
the demo.

## Run the judge demo

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, npm,
and `curl`.

```bash
./demo.sh
```

Then open:

- Patient flow: <http://localhost:3000>
- Projector/QR experience: <http://localhost:3000/present>
- Backend API docs: <http://localhost:8000/docs>

The first run installs locked dependencies, seeds the local file store, builds
the production frontend, and starts both services. Press `Ctrl+C` to stop them.

For the shortest judge path, open `/present`, scan the QR code, choose the
example bill, and send it to the screen. The result demonstrates two deliberately
different conclusions:

| Code | Synthetic billed amount | Real published cash price | Result |
| --- | ---: | ---: | --- |
| CPT 80053 | $1,385.59 | $860.00 | $525.59 above; review opportunity |
| CPT 71046 | $1,100.00 | $1,187.00 | $87.00 below; no positive discrepancy |

Every displayed benchmark includes its public source, effective date, retrieval
date, and record locator. See [DEMO.md](DEMO.md) for the 90-second presentation
script and venue fallback plan.

## What is included

```text
frontend/   Next.js 16 patient flow, projector screen, and same-origin BFF
backend/    FastAPI REST API, FastMCP tools, deterministic analysis, and storage
docs/       Product, matching, data, privacy, and integration contracts
artifacts/  Redacted local storage inventory and a no-write cleanup plan
```

Browser requests remain on `/api/v1/*`. A server-only Next.js route forwards
them to FastAPI using `BACKEND_API_URL`; the browser never receives the backend
origin, MongoDB credentials, signed download credentials, or the raw case token.
The token is held in an HttpOnly cookie and injected only for case-scoped calls.

## Product truth

- The example bill is synthetic; the cited hospital price evidence is real.
- Runtime price evidence must be `is_synthetic=false`, carry complete provenance,
  and belong to an active source manifest in `nrv_core_v1`.
- Inova and seeded urgent-care references are not active demo facilities.
- A public cash price is a comparison anchor, not a promise of what an insured
  patient should pay.
- Medicare data is labeled as reference context, never patient-paid data.
- BillBuster identifies review opportunities; it does not make legal, fraud, or
  medical-necessity determinations.

## Verification

The submission gate currently passes:

- 119 backend tests and Ruff
- 16 frontend tests, TypeScript, and the Next.js production build
- active-market readiness for both hospitals and both hero codes
- same-origin creation, upload, analysis, packet, presentation, and cascade
  deletion smoke tests
- repository and browser-bundle secret scans

Run the gates yourself:

```bash
cd backend
uv sync --extra dev --frozen
uv run pytest -q
uv run ruff check .
uv run python scripts/seed.py
uv run python -m scripts.readiness

cd ../frontend
npm ci
npm test
npm run typecheck
BACKEND_API_URL=http://127.0.0.1:8000 npm run build
```

## Documentation

- [START-HERE.md](START-HERE.md) — local development and backend-only checks
- [DEMO.md](DEMO.md) — judge script and fallback plan
- [DEPLOY.md](DEPLOY.md) — backend and Vercel environment/deployment sequence
- [Integration report](docs/FRONTEND_BACKEND_INTEGRATION.md) — route matrix,
  security boundary, Mongo inventory, and verification evidence
- [Backend README](backend/README.md) and [frontend README](frontend/README.md)

BillBuster is a hackathon prototype, not medical, legal, or financial advice.
