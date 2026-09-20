# BillBuster frontend

Mobile-first Next.js app over the BillBuster REST API, plus a projector page with
a QR code so people in the room can run the flow on their own phones.

## Demo day, in four commands

```bash
# 1. backend (from ../backend, once per machine)
cp .env.example .env && uv sync --extra dev && uv run python scripts/seed.py
uv run uvicorn billproof.api.main:app --host 127.0.0.1 --port 8000

# 2. frontend (from this directory)
npm install
npm run present           # builds, then serves on 0.0.0.0:3000
```

Then open **<http://localhost:3000/present>** on the projector. It shows the QR
code, the URL, and whether the backend is up and seeded.

Phones only ever talk to port 3000. The server-side route handler at
`app/api/v1/[...path]/route.ts` proxies `/api/v1/*` to the backend, so port 8000
never has to be reachable from the network and there is no CORS configuration
to get wrong. Copy `.env.example` to `.env.local` before starting the frontend.

## Making the QR code reachable

The `/present` page picks its QR target in this order:

1. `?url=` on the page, `http://localhost:3000/present?url=https://abc.trycloudflare.com`
2. `PUBLIC_URL` in the environment
3. This laptop's detected Wi-Fi address (used automatically when you open the
   page on localhost)
4. Whatever host the browser used

Option 3 is enough when the laptop and the phones share a network. **Plenty of
venue Wi-Fi blocks device-to-device traffic**, so test it early with a phone. If
it fails, run a tunnel and use option 1 or 2:

```bash
cloudflared tunnel --url http://localhost:3000     # or: ngrok http 3000
PUBLIC_URL=https://your-tunnel-url npm run present
```

A tunnel also gives you HTTPS, which phone cameras and clipboard copy prefer.

## Screens

| Route | What it is |
|---|---|
| `/` | The patient flow: start → bill → check lines → comparison → packet |
| `/?room=CODE` | Send-only mode: the phone hands a bill to the screen and stops |
| `/present` | The projector: QR code, and the comparison people send to it |

### The presentation screen

`/present` opens a capability room, shows a QR pointing at `/?room=<code>`, and
polls for the bill currently in that room. A phone that scans it runs the normal
flow, pick the example bill or enter their own, and then **publishes** the
finished comparison to the room. The phone shows a confirmation, never a
comparison; the analysis is displayed on the screen instead.

Each submission replaces the previous one, so only the bill currently on the wall
is retained. `DELETE /api/v1/screens/<code>` clears it between runs.

Two privacy rules hold for anything that reaches the wall, because it is projected
in a room full of people:

- The case access token is held in an HttpOnly, same-site cookie and is never
  exposed to browser JavaScript. The screen polls a token-free display copy
  that also omits private case, analysis, line, and price-record identifiers.
- Free text a person typed never reaches the screen. Masking catches emails,
  phones, labeled IDs and addresses, but no regex catches a name reliably, so
  hand-entered descriptions are dropped and lines are titled by billing code. The
  synthetic example bill keeps its descriptions, since its text ships with the repo.

The flow has two entry points:

- **Try the example bill**, `POST /api/v1/demo/cases`. A synthetic bill against
  a real hospital's real published prices, labeled as synthetic everywhere,
  including in the packet. Works with no internet at all.
- **Check my own bill**, pick a hospital and coverage, then upload a PDF or text
  bill or type the lines. Extraction returns editable candidates; nothing is
  compared until the person confirms them.

`public/samples/` holds the sample bill (`demo_bill.pdf`, `demo_bill.txt`) so a
judge with no bill on their phone can still exercise the upload path.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_API_URL` | required | Server-only backend origin, for example `http://127.0.0.1:8000` locally or the Railway origin on Vercel |
| `PUBLIC_URL` | unset | Forces the QR target (a tunnel or your domain) |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | `4` | Browser-side upload guard, kept under the host's proxy body limit |
| `ROOM_CODE` | random per `/present` load | Optional 12-32 character capability code; set a high-entropy value only when the room must survive reloads |
| `BFF_TIMEOUT_MS` | `60000` | Maximum time the proxy waits for the backend |
| `BFF_MAX_REQUEST_BYTES` | `5242880` | Maximum request body accepted by the proxy |
| `BFF_MAX_RESPONSE_BYTES` | `10485760` | Maximum response body accepted from the backend |

`BACKEND_API_URL` is read only by the Next server and is never included in a
browser bundle. The legacy server-only name `BACKEND_URL` remains accepted for
a zero-downtime environment-variable migration, but new deployments should use
`BACKEND_API_URL`.

## Deploying to a custom domain

See [../DEPLOY.md](../DEPLOY.md) for the full path: backend on Railway, frontend on
Vercel, and the exact GoDaddy CNAME record.

## Notes for whoever picks this up

- Every user-facing string lives in `lib/labels.ts`, so the wording rules in
  `docs/01-product-truth.md` can be reviewed in one place. No "overcharge", no
  "savings", no legal claims.
- The app never collects a name, date of birth, account number, or member ID.
  Only the case ID and non-secret resume metadata are kept in `sessionStorage`;
  the credential stays in an HttpOnly cookie. The case can be deleted from the
  results screen.
- The UI is English only for now. The **packet** is available in English and
  Spanish because the backend templates are. Translating the UI is the obvious
  next step, since docs/01 treats Spanish as primary.
- Amounts in comparison results arrive as integer cents and are formatted for
  display only; no arithmetic happens in the browser.
