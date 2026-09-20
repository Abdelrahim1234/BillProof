# Frontend/backend integration

## Source and deployment identity

The submission is a monorepo containing `frontend/` (Next.js 16.3.5 / React
19.3) and `backend/` (Python 3.12+, FastAPI, FastMCP, and PyMongo). The
integration work was reconciled on top of Git `main` commit
`8ea9a66f5e9ad57d35b7c6ca7e350ed34b79f2b7`.

The live Vercel deployment commit/project linkage was not available from the
local workspace and remains unreconciled. Its `/api/v1/hospitals` route was a
working same-origin proxy to a Railway backend, not a mock, but its price
response proved that deployment is stale because it returned a signed source
query that this revision strips.

## Outcome and architecture

BillBuster uses one same-origin browser contract. Browser code calls only
`/api/v1/...`; the Next.js server route at
`frontend/app/api/v1/[...path]/route.ts` forwards those calls to the FastAPI
origin in the server-only `BACKEND_API_URL` variable.

This is Option A (a thin backend-for-frontend). It does not query MongoDB or
duplicate analysis, extraction, matching, or pricing logic. Every business
operation remains in FastAPI.

The proxy:

- permits the existing HTTP methods, path, query, JSON, and multipart bodies;
- preserves the original multipart boundary;
- forwards only `Accept`, `Accept-Language`, `Content-Type`, and `If-Match`;
- enforces same-origin mutations, a 60-second upstream timeout, a 5 MiB request
  limit, and a 10 MiB response limit by default;
- returns backend status codes and safe bodies while replacing network/config
  failures with bounded JSON errors;
- exposes only `Content-Type` and the safe request ID from upstream responses;
- uses `Cache-Control: no-store` for every patient/public API response; and
- never puts the backend origin in browser runtime configuration.

The FastAPI case token is returned once to the proxy, removed from the browser
response, and stored as an HttpOnly, `SameSite=Lax` cookie scoped to `/api/v1`.
Browser JavaScript and `sessionStorage` keep only the case ID and non-secret
resume state. The proxy injects the token only on protected `/cases/{id}/...`
requests and clears the cookie after deletion or an authentication failure.
Authentication failures are distinguished from active-market policy failures:
an inactive legacy case cannot be read or processed, but its valid capability
and saved case ID remain available in a delete-only recovery screen so the
owner can still purge it.

## Route contract matrix

| UI action | Frontend caller | Method/path | Backend operation | Final status |
| --- | --- | --- | --- | --- |
| Liveness/readiness | `api.ready` | `GET /api/v1/ready` | storage ping + active-market/evidence gate | Connected |
| Load hospitals | `api.hospitals` | `GET /api/v1/hospitals` | two `nrv_core_v1` hospitals only | Connected |
| Load one hospital | `api.hospital` | `GET /api/v1/hospitals/{id}` | active-market facility lookup | Connected |
| Load price hints | `api.cashPrices` | `GET /api/v1/prices/search` | eligible real/current/provenanced prices | Connected |
| List examples | `api.demoSamples` | `GET /api/v1/demo/samples` | privacy-safe synthetic bill catalogue | Added/connected |
| Start example | `api.demoCase` | `POST /api/v1/demo/cases` | creates a private case and synthetic bill lines | Connected |
| Start own case | `api.createCase` | `POST /api/v1/cases` | validates active hospital, creates private case | Connected |
| Upload bill | `api.extract` | `POST /api/v1/cases/{id}/bill/extract` | bounded, non-persistent extraction | Connected |
| Confirm lines | `api.saveLines` | `POST /api/v1/cases/{id}/lines/bulk` | stores confirmed private lines | Connected |
| Resume bill | `api.getBill` | `GET /api/v1/cases/{id}/bill` | lists case-scoped lines | Connected |
| Analyze | `api.analyze` | `POST /api/v1/cases/{id}/analysis` | deterministic backend analysis | Connected |
| Resume result | `api.latestAnalysis` | `GET /api/v1/cases/{id}/analysis/latest` | latest stored analysis | Connected |
| Build packet | `api.packet` | `POST /api/v1/cases/{id}/packet` | backend packet service | Connected |
| Ask/explain | `api.askCase`, `api.explainLine` | `POST /api/v1/cases/{id}/ask` and `/lines/{line_id}/explain` | consent-gated explanation service | Connected |
| Send to wall | `api.publishToScreen` | `POST /api/v1/cases/{id}/publish` | privacy-reduced display copy | Added/connected |
| Poll/clear wall | `api.screenLatest`, `api.clearScreen` | `GET /api/v1/screens/{room}/latest`, `DELETE /api/v1/screens/{room}` | ephemeral room state | Added/connected |
| Delete case | `api.deleteCase` | `DELETE /api/v1/cases/{id}` | verified parent/child cascade, including wall copy | Connected |

The presentation copy never contains a case token or private case, analysis,
line, or price-record identifier. It uses short display-only line keys, and
user-entered descriptions are removed before a real bill reaches a shared
screen; bundled synthetic demo descriptions may remain. The one frontend demo sample produces the intended
opposite conclusions from real LewisGale evidence: CPT 80053 is above the
published cash price and CPT 71046 is below it.

## Runtime evidence scope

Out-of-scope rows may remain in storage, but runtime queries require:

- a facility named in `ACTIVE_MARKET_FACILITIES` (`nrv_core_v1` defaults to
  LewisGale Montgomery and Carilion NRV);
- `is_synthetic` explicitly equal to `false`;
- a non-empty source record locator;
- an active source manifest with a SHA-256 value; and
- a source URL matching that active manifest after query removal.

These constraints apply at repository boundaries used by REST, MCP, analysis,
peer matching, map evidence, and readiness. Public serialization strips URL
queries from price, facility, assistance, and regional-source links.

## Local run

Start the backend:

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run python scripts/seed.py
uv run uvicorn billproof.api.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start the frontend:

```bash
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

Open `http://localhost:3000`. To verify the backend without the frontend:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/ready
curl -fsS http://127.0.0.1:8000/api/v1/hospitals
```

## Environment variables

Vercel Preview and Production need these names (values belong in Vercel, not
source):

- `BACKEND_API_URL` (required, server-only public HTTPS FastAPI origin)
- `BFF_TIMEOUT_MS`
- `BFF_MAX_REQUEST_BYTES`
- `BFF_MAX_RESPONSE_BYTES`
- `NEXT_PUBLIC_MAX_UPLOAD_MB`
- `PUBLIC_URL` and optional high-entropy `ROOM_CODE` when using presentation mode

The backend host uses:

- `STORAGE_BACKEND`
- `PRIVATE_DB_NAME`, `PUBLIC_DB_NAME`
- `MONGODB_URI`, `MONGODB_PRIVATE_DATABASE`, `MONGODB_PUBLIC_DATABASE`
- `MONGODB_ALLOW_REMOTE`, `MONGODB_SERVER_SELECTION_TIMEOUT_MS`
- `MONGODB_CLEANUP_WRITES_ENABLED` (must stay false during review)
- `ACTIVE_MARKET_ID`, `ACTIVE_MARKET_FACILITIES`
- `CASE_TOKEN_SECRET`, `HMAC_IDENTIFIER_KEY`
- `CORS_ORIGINS`
- optional explanation/extraction provider variables from `backend/.env.example`

Vercel cannot use `localhost` for `BACKEND_API_URL`. Do not prefix backend or
Mongo variables with `NEXT_PUBLIC_`.

## Mongo inventory and cleanup status

The storage layer supports the explicit local file backend and PyMongo's async
client. Merely setting `MONGODB_URI` does not enable MongoDB; remote Mongo also
requires `STORAGE_BACKEND=mongodb` and `MONGODB_ALLOW_REMOTE=true`.

The checked-in review artifacts were generated from the current local file
store, not Atlas:

- `artifacts/mongo_inventory.json` — redacted counts/index/source metadata;
- `artifacts/mongo_cleanup_plan.md` — deterministic dry-run plan; and
- `artifacts/mongo_cleanup_manifest.private.json` — exact IDs, mode 0600 and
  gitignored.

The current dry run proposes zero quarantines and no deletion. Duplicate groups
are reported for human provenance review and are not auto-selected. Do not run
`--apply` against Atlas until the target, reviewed plan ID, current backup, and
rollback path have explicit approval.

The submission's redacted **clean local file-store** inventory contains six
collections:

- public: 6 facilities, 2 active source manifests, 21 non-synthetic price
  records, and 8 service bundles;
- private: empty case and bill-line collections after the cascade check;
- active market: 2 configured and 2 matching facilities;
- orphan references: 0 across every checked relationship;
- missing required provenance: 0 price rows and 0 source manifests; and
- deterministic duplicate groups: 0.

Dry-run plan `b42fd3747cc80e92ac331ca2` targets only explicit synthetic price
rows lacking lifecycle fields. Its exact expected count is 0. No backup was
confirmed, no cleanup was applied, and permanent deletion is not implemented.

## Verification performed

- Backend: 119 tests passed; Ruff passed; `uv lock --check` passed; OpenAPI
  3.1 generated successfully with 31 paths.
- Frontend: 16 tests passed; TypeScript passed; Next.js 16 production build
  passed with `/`, `/present`, and `/api/v1/[...path]` routes.
- Deployment config: `docker compose config --quiet` passed.
- Data/security: active-market readiness returned `READY`; the repository
  secret scan found no signed URL outside fake tests; the built browser chunks
  contained no backend origin, Mongo variable/URI, signed query, or case token.
- Local production-mode smoke: same-origin case creation, analysis, packet,
  multipart text upload, presentation publish/read, case deletion, and display
  cascade passed. CPT 80053 was $525.59 above the $860 cash price; CPT 71046
  was $87 below the $1,187 cash price. Both citations were real,
  non-synthetic, and query-free.

No frontend lint command exists in this package, so TypeScript, Node tests,
and the production build are the frontend static gates. No Vercel Preview or
Atlas connection was created during this pass.

## Implementation touchpoints

The integration implementation is contained in these source touchpoints:

- frontend boundary: `frontend/app/api/v1/[...path]/route.ts`,
  `frontend/lib/backend-proxy.ts`, `frontend/lib/api.ts`,
  `frontend/app/page.tsx`, `frontend/app/present/page.tsx`,
  `frontend/components/AskAI.tsx`, `frontend/components/Results.tsx`, and
  `frontend/next.config.ts`;
- frontend config/tests/docs: `frontend/.env.example`,
  `frontend/.gitignore`, `frontend/package.json`, `frontend/tsconfig.json`,
  `frontend/tests/api.test.ts`, `frontend/tests/backend-proxy.test.ts`, and
  `frontend/README.md`;
- backend storage/admin: `backend/src/billproof/config.py`,
  `backend/src/billproof/store.py`, `backend/src/billproof/admin/`,
  `backend/scripts/mongo_inventory.py`, `backend/scripts/mongo_cleanup.py`,
  `backend/pyproject.toml`, and `backend/uv.lock`;
- backend runtime contract: `backend/src/billproof/api/dependencies.py`,
  `backend/src/billproof/api/main.py`, the `cases`, `health`, `hospitals`,
  `map`, `packets`, and `screens` route modules, `backend/src/billproof/models.py`,
  `backend/src/billproof/mcp_server.py`, the `hospitals`, `prices`, and
  `case_records` repositories, and the analysis/map/privacy services;
- backend regression coverage: `backend/tests/integration/test_frontend_contract.py`,
  the case/analysis/map/MCP/seed integration tests, and the matching,
  manifest-sanitization, Mongo-admin, and storage-backend unit tests;
- runtime/deployment docs and config: `backend/.env.example`,
  `backend/.dockerignore`, `backend/.gitignore`, `backend/Dockerfile`,
  `backend/docker-compose.yml`, `backend/README.md`, `backend/docs/`,
  root `.gitignore`, `.claudeignore`, and `START-HERE.md`; and
- review artifacts: `artifacts/mongo_inventory.json` and
  `artifacts/mongo_cleanup_plan.md`. The exact-ID private manifest is
  gitignored and mode `0600`.

## Deployment status and required manual steps

Read-only checks on 2026-09-20 showed that the current Vercel site already
proxies healthy `/api/v1/health` and `/api/v1/hospitals` responses from a
Railway-hosted backend. That deployment is not this integrated source revision:
its public price-search response exposed a signed source query credential.

Before production:

1. Revoke/rotate the exposed signed credential if the source owner permits it.
2. Deploy this backend revision to the existing backend host or a reviewed
   preview host; do not expose MongoDB to Vercel/browser code.
3. Set `BACKEND_API_URL` in Vercel Preview and run the complete synthetic demo,
   upload, result, packet, presentation, and deletion flows.
4. Run the read-only inventory and cleanup dry-run against the intended Atlas
   target and review the newly generated plan. Do not apply it yet.
5. Compare Preview desktop/mobile rendering with the current production UI.
   No CSS, layout, typography, navigation, or component styling was changed in
   this integration pass, but baseline screenshots were not captured locally.
6. Obtain approval before any cleanup apply or Production deployment.

If Atlas already has the legacy `cases_expires_at_ttl` index, review and drop
that parent-only TTL before production and schedule
`scripts/purge_expired_cases.py`; the cascade-safe purge owns case retention.

Until those preview and Atlas checks run, local integration is complete but the
production rollout is intentionally not claimed complete.
