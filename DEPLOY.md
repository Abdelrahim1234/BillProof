# Deploying BillProof to a custom domain

Goal: judges open `https://www.thebillbuster.health` on their own phones, over cellular,
with nothing depending on the venue Wi-Fi or on your laptop staying awake.

Shape of it:

```
phone ──HTTPS──> www.thebillbuster.health (Vercel, frontend)
                       │  server-side proxy of /api/v1/*
                       └──HTTPS──> billproof-api.up.railway.app (Railway, backend)
```

Only the frontend needs DNS. The backend keeps its platform URL, so there is one
public hostname, one certificate, and no CORS configuration.

---

## 1. Backend on Railway

The backend is already a Docker image. `backend/start.sh` seeds the price data on
boot and listens on the `PORT` the platform injects.

1. [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo** → pick this repo.
2. Service **Settings**:
   - **Root Directory**: `backend`
   - **Builder**: Dockerfile (Railway detects `backend/Dockerfile` automatically)
   - **Health check path**: `/api/v1/health`
3. **Variables** — none are required. Useful ones: `CASE_TTL_HOURS`, `LOG_LEVEL`,
   `DEMO_MODE`. Do **not** set `PORT`; Railway injects it.
4. **Settings → Networking → Generate Domain**. Copy the `https://…up.railway.app` URL.
5. Check it: `curl https://your-api.up.railway.app/api/v1/ready` → `"seeded": true`.

Two things to know:

- **Storage is ephemeral.** SQLite lives in the container, so cases and analyses
  disappear on redeploy or restart. Cases expire in 24h by design, so this is fine
  for a demo. For persistence, add a Railway Postgres and set
  `DATABASE_URL=postgresql+psycopg://…` — the app supports it with no code change.
- **Cost.** New accounts get a one-time $5 trial credit; after that Hobby is $5/month,
  and the post-trial free plan only grants $1/month of credit. Fly.io is an equivalent
  alternative and uses the same Dockerfile. Avoid Render's free tier: it sleeps, and a
  cold start in front of judges is a bad demo.

## 2. Frontend on Vercel

1. [vercel.com](https://vercel.com) → **Add New → Project** → import this repo.
2. **Root Directory**: `frontend`. Framework preset: Next.js (auto-detected).
3. **Environment Variables** (Production):

   | Name | Value |
   |---|---|
   | `BACKEND_URL` | `https://your-api.up.railway.app` |
   | `NEXT_PUBLIC_MAX_UPLOAD_MB` | `4` |
   | `ROOM_CODE` | `billproof` (any 3-32 letters, digits or hyphens) |

4. Deploy, then check the `*.vercel.app` URL end to end: the example bill, then a
   packet.

> **`BACKEND_URL` is read at build time.** Next.js bakes the proxy destination into
> the build output, so changing this variable does nothing until you **redeploy**.
> This is the most common way to end up with a frontend that can't reach its API.

`NEXT_PUBLIC_MAX_UPLOAD_MB` is a browser-side guard. Hosted platforms cap the body of
a proxied request below the backend's own 10 MB limit, so the app refuses larger files
with a clear message instead of failing at the edge. If real uploads fail, lower it.

## 3. DNS

The project domain is `thebillbuster.health`, registered at **Porkbun**, with
Porkbun's nameservers. Records go in Porkbun's panel — not GoDaddy's, which is not
authoritative for this domain. (If you later move the domain to GoDaddy, the same
records apply; GoDaddy's quirks are noted at the end.)

`www` is the primary hostname, which is the easy case: a subdomain takes a CNAME
anywhere.

1. In Vercel: **Project → Settings → Domains**, add **both**
   `www.thebillbuster.health` and `thebillbuster.health`, and set **www as
   primary** so the bare domain redirects to it.
2. Vercel shows the exact records. **The CNAME value is project-specific**,
   something like `d1d4fc829fe7bc7c.vercel-dns-017.com` — copy it from your
   dashboard. Values from blog posts or older docs will not verify.
3. In Porkbun: **Domain Management → thebillbuster.health → Details → DNS Records**.

   First **delete the default parking records** (Porkbun's `pixie.porkbun.com`
   entries, which currently answer `208.66.192.100` for both names). A leftover A
   or ALIAS record on the same host is the usual reason a domain sits on "Invalid
   Configuration".

   Then add:

   | Type | Host | Answer | TTL |
   |---|---|---|---|
   | `CNAME` | `www` | the value Vercel shows | 600 |
   | `A` | *(leave blank — blank means the apex)* | `76.76.21.21` (confirm in Vercel) | 600 |

   Porkbun also supports `ALIAS` at the apex if you would rather not hard-code
   Vercel's IP; point it at the same hostname Vercel gives for the apex.

4. Wait for Vercel to flip both domains to **Valid Configuration**; certificates
   issue automatically. Usually minutes.

Check from a terminal:

```bash
dig +short www.thebillbuster.health     # should show the vercel-dns value
dig +short thebillbuster.health         # should show Vercel's apex IP
curl -sI https://www.thebillbuster.health   # 200, valid TLS
```

### Notes

- **Do not use URL forwarding** (Porkbun's forwarding, or GoDaddy's) to point at the
  Vercel URL. It redirects or frames rather than serving your domain, which breaks
  HTTPS and makes the QR code useless.
- **On GoDaddy specifically**, the apex cannot be a CNAME — use the A record above.
  Porkbun does not have this limitation because it offers ALIAS.
- If you ever move nameservers, copy MX and TXT records first or you will silently
  lose email on the domain.

## 4. Point the QR code at the domain

Nothing to configure. `/present` uses the host the browser asked for, so opening
`https://www.thebillbuster.health/present` produces a QR for
`https://www.thebillbuster.health/?room=<ROOM_CODE>` — the send-only phone page that
feeds the screen.

Because `ROOM_CODE` is fixed in your environment, that QR is stable: you can put it
on a slide or a poster and it keeps working across restarts and redeploys.

To force a specific target — say you want the QR to read `https://yourdomain.com`
while you're on the Vercel URL — set `PUBLIC_URL` in Vercel, or open
`/present?url=https://whatever` for a one-off.

## 5. Pre-demo checklist

```bash
curl -s https://www.thebillbuster.health/api/v1/ready      # {"status":"ok","seeded":true}
```

Then on an actual phone, **on cellular with Wi-Fi off**:

1. Scan the QR on `/present`.
2. Send the example bill → it appears on the screen within a few seconds.
3. Send a second bill → it replaces the first.
4. Open `https://www.thebillbuster.health/` directly (no `?room=`) and confirm the full
   personal flow still ends in a packet.

Do this the night before. DNS propagation and a first certificate issuance are not
things you want to discover on stage.
