# BillBuster release status

The judge-demo implementation is complete. `README.md`, `START-HERE.md`, and
`DEMO.md` are the operational entry points; this file records the final scope
and verification state.

## Delivered

- Next.js 16 patient flow and projector/QR presentation screen.
- Server-only same-origin API proxy with HttpOnly case sessions, origin checks,
  bounded bodies, timeouts, and response/header filtering.
- FastAPI REST API and `mcp==1.30.0` FastMCP server over shared deterministic
  services.
- Explicit local JSON-file storage for the offline demo and optional guarded
  MongoDB storage through the same repositories.
- Idempotent startup index initialization, cascade deletion, expired-case purge
  command, and presentation-copy expiry enforcement on public reads.
- A synthetic, identifier-free hero bill with 21 verified non-synthetic public
  price rows from official LewisGale Montgomery and Carilion NRV MRFs.
- Two deliberately different hero conclusions: CPT 80053 is $525.59 above the
  disclosed cash price; CPT 71046 is $87.00 below it.
- Query-free citations with publisher, source/effective/retrieval dates, exact
  record locators, and explicit limitations.
- Deterministic English/Spanish negotiation packets and a server-local grounded
  explanation assistant that requires no API key or network.
- Optional consent-gated Gemini explanation mode; calculations and citations
  always remain code-owned.
- Redacted storage inventory and reversible, dry-run-first Mongo cleanup plan.

## Active market and data boundary

`nrv_core_v1` contains exactly:

- LewisGale Hospital Montgomery
- Carilion New River Valley Medical Center

Inova and urgent-care reference identities may exist as inactive metadata, but
runtime hospital lookup, evidence, matching, analysis, map results, screens, and
readiness exclude them. Full multi-gigabyte MRFs are not committed.

## Release gates

- 119 backend tests pass; Ruff and `uv lock --check` pass.
- 16 frontend tests pass; TypeScript and the Next.js production build pass.
- Active-market readiness reports `READY`, 21 real price rows, zero synthetic
  price rows, both hero codes, query-free sources, and cascade deletion.
- The production-mode same-origin smoke test covers case creation, HttpOnly
  session handling, bill read, analysis, packet, built-in explanation,
  presentation publish/poll, and deletion.
- Repository and browser-boundary scans find no credentials or signed URL query
  values. The exact-ID cleanup manifest, local stores, environments, caches, and
  build output remain gitignored.
- Docker Compose configuration parses. A local image build could not be executed
  because Docker Desktop's daemon was not running; the same container entrypoint
  was exercised directly by `./demo.sh`.

## Intentional limitations

- The demo identifies review opportunities; it does not determine what a patient
  owes or claim fraud, illegality, or guaranteed savings.
- OCR for image-only scans, malware scanning, object storage, PDF packet export,
  Turquoise integration, and external PDF extraction are not implemented.
- Regional, Medicare, and plan-benefit benchmark collections have no live seed
  rows; those paths return honest empty/insufficient-data states.
- `peer_percentile` remains disabled for the two-hospital market, so the hero
  label is “Strong review opportunity,” not “High review opportunity.”

## Hosted deployment requirements

For MongoDB hosting, use server-only secrets, the explicit remote opt-in, a
reviewed target fingerprint, and the startup-created index plan. Schedule
`scripts/purge_expired_cases.py`, remove any legacy parent-only case TTL index,
rotate any previously exposed signed MRF credential, and pass the preview gate
in `DEPLOY.md` before promotion.
