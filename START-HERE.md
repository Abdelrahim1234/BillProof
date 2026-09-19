# How to use this kit

## What it is

Your three documents, restructured so Claude Code carries the project's context
in the repo instead of you re-pasting it every session.

```
CLAUDE.md              ← auto-loaded every session. The invariants.
BUILD_BACKEND.md       ← the one prompt you paste. Points at the docs.
docs/01-product-truth.md        Language, labels, safety, accessibility
docs/02-data-contract.md        Enums, JSON, models, ingestion, extraction, .env
docs/03-matching-and-scoring.md Matching tiers, benchmarks, confidence, score
docs/04-api-and-mcp-contract.md Repo layout, REST, MCP, tests
docs/05-proofmap.md             Facilities, map, evidence, cost-share
docs/99-human-tasks.md          What you have to do by hand
```

## Setup (2 minutes)

```bash
cd <your-repo>
# copy CLAUDE.md to the repo root and docs/ alongside it
git add CLAUDE.md docs/ && git commit -m "Add project context for Claude Code"
```

Then open Claude Code in the repo root and paste the contents of
`BUILD_BACKEND.md` as your first message.

## Why this shape

**`CLAUDE.md` is the important file.** Claude Code loads it automatically on
every session and every compaction, so the ten invariants survive context resets.
That is the "project understands what it's doing" part — in a 1,000-line pasted
prompt, rule #3 is forgotten by hour six; in `CLAUDE.md` it is re-read constantly.

**The docs are referenced, not pasted.** `BUILD_BACKEND.md` tells the agent which
doc to read at which stage, so a matching-rules doc isn't sitting in context
while it writes Dockerfiles.

**`PROGRESS.md` is the resume handle.** The build prompt has the agent keep it
updated and re-read it after a context reset, so a compaction mid-Stage-6 doesn't
restart the build.

## What I changed from your originals

- **Deduplicated.** The cost-share formula appeared in all three files with
  slightly different variable names; the amount-type table appeared twice; the
  ProofMap endpoints appeared twice. One canonical copy each now.
- **Resolved a conflict.** The blueprint treats ProofMap as a second hero
  feature; the backend prompt says it "takes precedence if an earlier scope
  statement treats maps as optional." `CLAUDE.md` now states the precedence rule
  explicitly so the agent doesn't have to guess.
- **Cut the pitch material.** Sections 18–22 of the blueprint (demo script, judge
  Q&A, Devpost copy, track mapping) are ~200 lines the coding agent never needs.
  Keep them for yourself.
- **Flagged a likely bug in your own spec.** `CLAUDE_BACKEND_BUILD_PROMPT.md`
  hardcodes `from mcp.server import MCPServer` with `mcp[cli]>=2,<3`. If that
  import is wrong for the SDK version that actually installs, the agent will
  spend an hour fighting it and may invent a workaround. `CLAUDE.md` now tells it
  to verify the real export before writing tool code.
- **Moved ProofMap tables into Stage 2.** Your original order adds them late,
  which means a schema migration mid-hackathon. They're free to create upfront.
- **Pulled out human-only work.** Verifying real MRF rows and urgent-care
  locations is the one thing that decides whether your demo has real cited prices.
  It can't be delegated to the CLI and it was buried in checkboxes across two
  files.

## Two things worth deciding before you start

1. **ProofMap in P0 or not?** It roughly doubles the backend surface — six more
   MCP tools, seven more endpoints, five more tables. If the team is 2–3 people,
   consider cutting it to P1 and editing Stage 8 out of `BUILD_BACKEND.md`. The
   core bill → comparison → packet flow is the thing judges score.
2. **Frontend prompt.** There isn't one in your three documents — only the
   backend brief exists. You'll want an equivalent `BUILD_FRONTEND.md` that
   consumes the OpenAPI schema this backend generates. Worth writing once Stage 4
   is green and the contract is stable.
