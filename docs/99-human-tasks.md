# 99 — Human-only tasks

Claude Code cannot do these. They block or degrade the build if nobody does them,
and they are the difference between a demo with real cited prices and a demo full
of synthetic placeholders.

## Blocking — do these in parallel with Stage 1–3

- [x] **Verify the current MRF URLs** for LewisGale Hospital Montgomery and
      Carilion New River Valley Medical Center. Try `https://<domain>/cms-hpt.txt`
      first, then the hospital's price-transparency page.
- [x] **Download the MRFs and pick 8+ source-verifiable rows.** Each selected
      row has an unambiguous code, code type, care setting, amount type, amount,
      and exact record locator. Source fields that are not published (including
      units or charge scope) must remain `unknown` and be disclosed rather than
      inferred. Candidates: emergency visit levels, chest X-ray, common lab
      panels, a CT scan.
- [x] **Do not lock the hero demo code** until a clean, current, defensible row is
      actually in hand.
- [x] **Drop the verified rows into `data/seed/public_prices.csv`** and record,
      across that extract and `data/seed/provenance.json`, the source URL, MRF
      last-updated date, retrieval timestamp, and record locator. Anything
      generated without a verified source must stay `is_synthetic=true`.
- [x] **Record the SHA-256 of each downloaded source file** into
      `data/seed/provenance.json`.

Verified 2026-09-19: the official `cms-hpt.txt` files resolve to a 325,667,881-byte
LewisGale JSON MRF (2026-09-01) and a 55,972,998-byte Carilion CSV MRF
(2025-12-15). The repository keeps a 21-row extract covering five shared CPTs;
the raw MRFs are not checked in. LewisGale's file jointly lists the Montgomery
hospital and Christiansburg FSER, and neither source states billing class or
service units for the selected rows. Those fields remain `unknown`, and the
exact limitations, hashes, retrieval times, and record locators are recorded in
`data/seed/provenance.json` and `data/seed/public_prices.csv`.

## Blocking — before ProofMap seeding (Stage 8)

- [ ] **Verify 5–10 urgent-care / clinic locations** near Blacksburg and
      Christiansburg: name, exact address, coordinates, facility type, NPI.
      NPPES is self-reported — confirm the location is real and open.
- [ ] **Keep at least one location with no public price.** The honest
      "No public price found" state is part of the pitch, not a gap.
- [ ] **Verify financial-assistance and billing URLs + phone numbers** for both
      demo hospitals.

## Non-blocking but needed before submission

- [ ] **Copy the exact onsite MCP track prompt**, sponsor, required technology,
      submission field, and judging condition — photograph it. Update the README
      and pitch to match that wording precisely.
- [x] Create the synthetic patient statement fixture. It must be visibly
      synthetic on screen and match one verified source row.
- [ ] Decide who answers data and privacy questions during judging.

## Things to say no to

- Do not put real patient bills into the repo, even redacted, even your own.
- Do not pay for or request Virginia APCD raw data for this build. Name it as the
  validated next phase.
- Do not bundle a proprietary CPT description library.
- Do not fetch multi-gigabyte files during the live demo, or during any request.

## Pitch material — deliberately kept out of the repo

The demo script, judge Q&A, Devpost copy, track mapping, and Ut Prosim framing
from the original blueprint are **not** in `docs/`. They are context the coding
agent does not need and would only burn tokens on. Keep them in the original
blueprint file, outside the repo or in a `pitch/` folder that `.claudeignore`
excludes.
