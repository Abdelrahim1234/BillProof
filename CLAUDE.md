# CLAUDE.md — BillBuster

Always-on rules. Everything here applies to every task in this repo. Detailed
specs live in `docs/`; read the one a phase prompt names, not all of them.

## What this project is

BillBuster turns a hospital bill into a citation-backed comparison against the
hospital's own publicly disclosed prices, plus a negotiation packet (phone
script, written request, evidence table, assistance path).

Backend: Python 3.12 / FastAPI / Pydantic 2 / explicit local-file or MongoDB
storage through `store.py` / official MCP Python SDK (`FastMCP`).
Frontend: Next.js 16 with a same-origin, server-only backend proxy.

## Non-negotiable invariants

Violating any of these is a bug even if tests pass.

1. **Never conflate amount types.** Gross/billed charge, discounted cash price,
   payer-negotiated rate, total allowed amount, insurer payment, patient
   responsibility, and de-identified allowed percentiles are seven different
   values. Every stored, compared, and displayed number carries its
   `charge_type` / `amount_type`.
2. **No source, no claim.** Every numeric claim returns a source URL, publisher,
   effective date, retrieval date, and a synthetic flag — or is explicitly
   labeled as arithmetic on user-confirmed values.
3. **Never say fraud, illegal, or guaranteed savings.** The product language is
   "potential billing discrepancy", "amount worth asking about", "review
   opportunity". The monetary delta is `potential_review_amount`, never
   "savings".
4. **Code does the math; models only draft prose.** No LLM output is ever a
   price, a difference, a score, a citation, or an eligibility determination.
5. **Money is `Decimal` in domain models and integer cents at the API
   boundary.** The file and Mongo adapters serialize exact decimal values;
   never use a binary float for money.
6. **REST and MCP call the same service classes.** MCP tools must not call
   localhost HTTP. There is no `/mcp` REST route pretending to be a protocol.
7. **Return `insufficient_data` rather than inventing a benchmark.** No midpoint
   of a de-identified min/max. No description-similarity match treated as a code
   match. No cross-code-system translation.
8. **Protected traits never enter pricing, matching, or scoring.** Changing name,
   locale, or any display metadata must not change a single number. Optional
   income/household size only powers assistance discovery.
9. **Privacy:** no patient name, DOB, street address, account number, MRN, member
   ID, email, or phone in any schema or table. Raw uploads are deleted in a
   `finally` block. Full extracted text is never persisted. Never log request
   bodies, tokens, protected MCP arguments, or extracted text.
10. **No HIPAA-compliance claim** anywhere in code, docs, UI copy, or README.

## Working agreement

- Inspect existing files before writing. Preserve unrelated work.
- Implement, run, and test — do not stop at a plan or pseudocode.
- Run the relevant tests after each stage. Never leave the repo knowingly broken.
- Ask a question only if a real blocker prevents progress. Otherwise pick the
  option most consistent with this file and note the choice in your final report.
- When a spec here disagrees with a doc in `docs/`, this file wins. When two
  docs disagree, the ProofMap doc is newer and wins on map/facility scope.

## SDK version caution

The original brief specified `from mcp.server import MCPServer` and
`mcp[cli]>=2,<3`. **Verify this against the SDK actually installed** before
writing tool code — check the installed package's exports and its README rather
than trusting that import line. If the installed SDK exposes a different entry
point, use the real one and record the difference in your final report.

## Commands that must keep working

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run python scripts/seed.py
uv run uvicorn billproof.api.main:app --reload
uv run pytest -q
uv run ruff check .
uv run mcp dev src/billproof/mcp_server.py

cd ../frontend
npm ci
npm test
npm run typecheck
npm run build
```

## Docs index

| File | Read it when |
|---|---|
| `docs/01-product-truth.md` | Writing any user-facing string, label, or disclaimer |
| `docs/02-data-contract.md` | Touching models, schemas, enums, JSON shape, ingestion |
| `docs/03-matching-and-scoring.md` | Touching matching, benchmarks, confidence, score, findings |
| `docs/04-api-and-mcp-contract.md` | Touching routes, auth, MCP tools/resources/prompts |
| `docs/05-proofmap.md` | Touching facilities, map search, evidence, cost-share |
| `docs/99-human-tasks.md` | Never — that file is for the humans on the team |

The generated `graphify-out/` tree and bundled cross-agent skill mirrors are not
part of the application or release workflow; they are gitignored.
