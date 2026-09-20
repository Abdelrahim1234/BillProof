# BillBuster judge demo

## Preflight

Run this before the judging window:

```bash
cd backend
uv run python -m scripts.readiness
cd ../frontend
npm test
```

Start the production-mode local demo from the repository root:

```bash
./demo.sh
```

Open <http://localhost:3000/present>. If phones cannot reach the laptop on venue
Wi-Fi, use the flow directly at <http://localhost:3000>, or provide an approved
HTTPS tunnel through `PUBLIC_URL`. Never put a case token or document data in a
URL.

## 90-second script

1. **Problem — 15 seconds.** “Hospital bills are hard to challenge because a
   patient usually cannot connect a line item to a comparable public price.”
2. **Trust boundary — 10 seconds.** “This bill is synthetic. The hospital prices
   are real rows extracted from official machine-readable files, and every number
   is cited.”
3. **Run it — 20 seconds.** Scan the projector QR code, choose the example bill,
   review its two lines, and send it to the screen.
4. **Show nuance — 25 seconds.** CPT 80053 is $525.59 above LewisGale's $860 cash
   price and is labeled a review opportunity. CPT 71046 is $87 below the $1,187
   price and is not presented as savings or an overcharge.
5. **Show action — 15 seconds.** Open the evidence and packet. Point out the
   source date, retrieval date, locator, limitations, and the questions a patient
   can actually ask billing staff.
6. **Close — 5 seconds.** “BillBuster does not decide what a patient owes. It gives
   them a defensible place to start the conversation.”

## Judge questions

**Are these real hospital prices?**

Yes. The public price rows are non-synthetic extracts from official LewisGale
Montgomery and Carilion NRV machine-readable files. The patient bill is synthetic
and is labeled as such.

**Why only two hospitals?**

The demo favors a small verified market over broad but unverifiable coverage.
Out-of-market facilities cannot enter matching, readiness, REST, or MCP results.

**Does “above” mean the bill is wrong?**

No. Amount type, care setting, payer, plan, units, and facility/professional scope
can change comparability. BillBuster exposes these limitations and recommends
questions instead of making a legal conclusion.

**Where is MongoDB?**

The repository contract supports a local file store for a no-network demo and an
explicit server-only MongoDB mode for hosting. The browser and Vercel client code
never connect to MongoDB.

## Offline fallback

The example path uses bundled fonts, the curated public-price seed, deterministic
analysis, and local storage. It does not need an AI key or an MRF download. If the
frontend cannot be used, demonstrate the backend at <http://localhost:8000/docs>
and verify it with:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/ready
curl -fsS http://127.0.0.1:8000/api/v1/hospitals
curl -fsS http://127.0.0.1:8000/api/v1/demo/samples
```
