# Deployment

BillBuster is a monorepo with an independently hosted FastAPI backend and Next.js
frontend. Deploy the backend first; Vercel cannot call a laptop's `localhost`.

## 1. Backend preview

Use the existing reviewed backend host or another approved Python container host.
The included `backend/Dockerfile` starts FastAPI on port 8000. Configure names
only through the host's secret/environment settings:

```text
STORAGE_BACKEND
MONGODB_URI
MONGODB_PRIVATE_DATABASE
MONGODB_PUBLIC_DATABASE
MONGODB_ALLOW_REMOTE
ACTIVE_MARKET_ID
ACTIVE_MARKET_FACILITIES
CASE_TOKEN_SECRET
HMAC_IDENTIFIER_KEY
CORS_ORIGINS
```

For hosted use, choose `STORAGE_BACKEND=mongodb`, keep `MONGODB_URI` server-only,
and deliberately enable the reviewed remote target. Run the redacted inventory
and readiness checks before exposing the preview. Do not point automated tests at
the production database.

FastAPI startup runs the idempotent `store.init_indexes()` plan before accepting
requests. Because case expiry deliberately uses a normal index so child records
can be cascade-deleted, configure the backend host to run this command on a
schedule (hourly is sufficient for the demo):

```bash
uv run python scripts/purge_expired_cases.py
```

Do not call a hosted Mongo deployment complete without that scheduler. Review
and remove any legacy parent-only `cases_expires_at_ttl` index first, as described
in `backend/docs/ATLAS_SETUP.md`.

## 2. Vercel preview

Create a Vercel project with `frontend` as its Root Directory. The framework is
Next.js and the lockfile supplies the install/build commands. Set:

```text
BACKEND_API_URL
BFF_TIMEOUT_MS
BFF_MAX_REQUEST_BYTES
BFF_MAX_RESPONSE_BYTES
NEXT_PUBLIC_MAX_UPLOAD_MB
PUBLIC_URL
ROOM_CODE
```

Only `NEXT_PUBLIC_MAX_UPLOAD_MB` is intentionally public. `BACKEND_API_URL` is a
server-only origin and must not contain credentials, a path, query, or fragment.
Leave `ROOM_CODE` blank to generate a fresh high-entropy presentation capability.

## 3. Preview gate

Using only the bundled synthetic/redacted bill:

1. Confirm `/api/v1/ready` reports `status=ok`, `db=ok`,
   `market_id=nrv_core_v1`, and `seeded=true`.
2. Confirm `/api/v1/hospitals` returns exactly LewisGale Montgomery and
   Carilion NRV.
3. Complete the example and upload flows.
4. Verify CPT 80053 is above and CPT 71046 is below the cited cash prices.
5. Open the stable, query-free evidence links.
6. Test the presentation room, built-in explanation, and packet.
7. Delete the case and confirm it and its presentation copy no longer load.
8. Inspect built browser assets for backend/Mongo/signed credentials.

Promote that exact preview only after the Atlas target, backup posture, and any
legacy TTL-index migration have been reviewed. The safe sequence and current
local inventory are documented in
`docs/FRONTEND_BACKEND_INTEGRATION.md` and `backend/docs/ATLAS_SETUP.md`.
