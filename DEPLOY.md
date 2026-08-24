# ArguMap — Deployment Guide

## Overview

ArguMap is a web application for creating, editing, and analysing ethical argument
maps. It consists of:

- **FastAPI** backend (`main.py`) serving a REST API and HTML map viewer
- **AntV X6** interactive graph editor (embedded in `automap_v2_x6.py`)
- **LLM pipeline** (`automap_v2_pipeline.py`) for automatic map extraction via Claude
- **SQLite** database for users, maps, and courses
- **Docker** container, reverse-proxied by Caddy with automatic HTTPS

The repository root is self-contained: all Python modules, templates, and data
files needed to run the server live here.

---

## Directory structure

```
.
├── main.py                   # FastAPI app — routes, auth, map viewer injection
├── models.py                 # SQLAlchemy models + DB init + seed data
├── auth.py                   # JWT auth (httpOnly cookie, 7-day tokens)
├── automap_v2_pipeline.py    # LLM extraction pipeline (4-step, Anthropic SDK)
├── automap_v2_x6.py          # X6 visualizer — generates standalone HTML pages
├── locales.py                # UI strings (EN / IT / DE)
├── schemes.json              # Inference rule / fallacy / bias vocabulary
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example              # Template — copy to .env (which is gitignored)
├── imgs/                     # Logos / favicon
├── static/                   # Static assets (may be empty; must exist)
├── templates/                # Jinja2 HTML templates
├── docs/                     # In-app user/teacher/admin manuals (en/it/de)
└── data/                     # SQLite DB — created at runtime, persisted via volume
```

> Module/file names keep the historical `automap_v2_*` prefix; only the product
> name changed to ArguMap.

---

## Prerequisites (server)

- Docker + Docker Compose plugin
- Caddy (or another reverse proxy) for HTTPS termination
- DNS A record pointing to the server IP

---

## First-time setup

### 1. Clone the repository

```bash
git clone https://github.com/that-ugly-cat/ArguMap.git /opt/apps/argumap
cd /opt/apps/argumap
```

### 2. Create the `.env` file

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY and JWT_SECRET
chmod 600 .env
```

Generate a secure JWT secret:
```bash
openssl rand -hex 32
```

### 3. Build and start

```bash
docker compose up -d --build
```

The database is created automatically on first startup by `init_db()` in
`models.py`, including seed roles and permissions. No manual SQL required.

### 4. Create the first admin user

```bash
docker exec -it argumap python - << 'EOF'
from models import SessionLocal, User, Role, init_db
from auth import hash_password
db = SessionLocal()
role = db.query(Role).filter(Role.name == "admin").first()
u = User(email="admin@example.com", password_hash=hash_password("changeme"), name="Admin", role=role, is_active=True)
db.add(u); db.commit()
print("Admin user created.")
EOF
```

### 5. Configure Caddy

The app is served at **argumap.borant.eu**. Add to `/etc/caddy/Caddyfile`:

```
argumap.yourdomain.tld {
    reverse_proxy localhost:8000
}


```

Then reload: `systemctl reload caddy`

**DNS:** add an `A` record for `argumap` → the VPS IP at the registrar before
reloading Caddy (Caddy needs the hostname to resolve to obtain the TLS cert).
The old `automap` record must stay in place for the redirect block to work.

---

## Updating an existing deployment

```bash
cd /opt/apps/argumap
git pull
docker compose up -d --build
```

Schema changes are applied automatically on startup (additive migrations in
`init_db()`); the SQLite DB under `data/` is preserved across rebuilds via the
Docker volume.

---

## Database

- Location on host: `data/maps.db` (bind-mounted into the container at `/app/data/maps.db`)
- Engine: SQLite with SQLAlchemy ORM
- Migrations: additive only, run automatically on every startup via `init_db()`.
  New columns are added with `ALTER TABLE`; failures (duplicate columns) are
  silently ignored.
- To add a new column: add it to the model in `models.py` AND add an `ALTER TABLE`
  line in the `init_db()` migration list.
- **Backup**: `cp data/maps.db data/maps.db.bak`

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | Yes | Secret key for JWT signing. Min 32 chars, random. |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for pipeline and debate features. |
| `PAPER2MD_URL` | No | PDF → clean-text service. Defaults to `https://paper2md.borant.eu`. |
| `PAPER2MD_API_KEY` | No | Optional key for paper2md; raises the upload size cap to 50MB. |

---

## Permission model

Roles and permissions are seeded automatically. The hierarchy is:

| Role | Permissions |
|---|---|
| `basic` | manual editor only |
| `standard` | manual + pipeline |
| `full` | manual + pipeline + debate |
| `teacher` | full + view all maps in own courses |
| `admin` | all permissions + admin panel |

---

## Logs

```bash
docker logs argumap          # all logs
docker logs argumap -f       # follow
docker logs argumap --tail 50
```

## Authentication: two modes, and the one thing to settle first

ArguMap authenticates on its own by default and needs no identity provider.
`AUTH_MODE=gateway` is a second mode, for a deployment behind an SSO gate that
speaks the `X-Borant-*` header contract.

```
AUTH_MODE=local     (default)   email + password against the users table
AUTH_MODE=gateway               the upstream gate vouches via X-Borant-Sub
```

**No role that can spend is ever provisioned from a header.** A profile created
from the gate gets `basic`, whatever the hint says, because `basic` has no
`pipeline` permission. This matters more here than elsewhere: `_check_budget`
returns immediately when `monthly_budget_usd` is NULL, and that is the current
state of every account. Promotion stays a human click in `/admin`.

`BORANT_TRUSTED_PROXY` is measured from the app's log after a real request, not
deduced. Local login and self-service registration close in `gateway`; logout
redirects to the gate's `GET /logout`, which asks — the POST is what revokes.

### The annotation endpoints do *optional* authentication

Three endpoints serve **both** an anonymous annotator and a logged-in owner
through the same URL:

```
GET    /api/maps/{id}/annotations       anonymous or owner
POST   /api/maps/{id}/annotations       anonymous or owner
GET    /api/maps/{id}/annotate/data     anonymous or owner
PATCH  /api/annotations/{id}            anonymous or owner
DELETE /api/annotations/{id}            anonymous or owner
```

and their siblings do not:

```
GET/DELETE /api/maps/{id}/annotations/detached   owner only
POST       /api/maps/{id}/annotate/open|close|new-session|anon   owner only
```

**Solved on 24/8/2026 by splitting the API by audience.** The same handlers now
answer on two prefixes, and the prefix decides the identity:

```
/api/maps/{id}/annotations        gated     the owner, with privileges
/annot/maps/{id}/annotations      public    anonymous, with none
/api/maps/{id}/annotate/data      gated
/annot/maps/{id}/data             public
/api/annotations/{id}             gated
/annot/annotations/{id}           public
```

Under `/annot` no user is ever looked up. That is worth stating precisely
because it is stronger than what a proxy can promise: send a valid
`X-Borant-Sub` from a trusted source to `/annot` and it still answers
"Anonymous". The property survives a proxy that fails to strip anything.

`/api/whoami` sits inside the gate and exists only for the annotation client.
From a share link the browser cannot tell whether it has an account, because
the public branch carries no identity by construction — so the client asks
once, with `Accept: application/json` so the gate answers 401 instead of
redirecting to a login page, and switches to the gated paths if it gets
through. Anyone with an account keeps their name on their annotations; anyone
without stays anonymous.

Public surface for the reverse proxy: `/healthz`, `/share/*`, `/annotate/*`,
`/join`, `/qr/*`, `/static/*`, `/imgs/*`, `/lang/*`, `/login`, `/register`, and
**`/annot/*`** — one clean prefix instead of a matcher picking single paths out
of `/api`.

**Deploy it when no annotation session is open in a room.** Three maps carry an
open session today; the client changes which URLs it calls, so a browser left
on the old page keeps calling the old ones until it is reloaded.

## Join codes (`/join`)

A map gets a six-digit code the first time its owner opens annotation, and
keeps it for good — one map, one code, reusable next year. `GET /join?c=NNNNNN`
resolves it to that map's `/annotate/{token}` **only while `annotate_open` is
true**, and `GET /qr/NNNNNN.svg` draws the QR (no DB lookup, so the QR route
cannot be used to discover which codes exist). The teacher gets the code, the
QR and a projector view in the map's Sharing panel.

Two deployment notes:

- **The proxy must let `/join` and `/qr/*` through the gate.** They are on the
  public list above. If they are not, a student typing a code lands on Borant
  ID instead of the exercise, which is exactly the friction the code exists to
  remove.
- **The QR encodes an absolute URL**, built from the `Host` header plus
  `X-Forwarded-Proto` when the request comes from `BORANT_TRUSTED_PROXY`.
  Uvicorn runs without `--proxy-headers`, so without that header the QR would
  say `http://`; Caddy sends it, and the fallback is a scheme the proxy
  redirects anyway.

Codes are six digits where RoomPulse uses five. In a session where both tools
are on the slides, a code typed into the wrong app fails on its length before
any lookup, instead of quietly resolving onto someone else's map.

Failed lookups are counted per client IP: past 30 in a minute the route sleeps
a second before answering, past 200 it returns 429. The soft step is
deliberate — a lecture hall is one NATed address, so a hard block after a few
dozen collective typos would lock out the students who typed correctly.

## The landing, the home, and the role hint

Same shape in every app of the perimeter, so there is nothing to remember per
tool.

**`/` is a public showcase and never asks who is reading it.** Not laziness: on
the public branch of the reverse proxy the `X-Borant-*` headers are stripped by
construction, so a branch on the user is always false behind the gate and
sometimes true without one — the same page with two behaviours. By not asking,
the page is identical in both modes and one button covers all four cases:
gated or standalone, already signed in or not. It also shows no internal
counts: anyone can read it.

**The app lives at `/app`**, which is gated, and the showcase's button
points there — not at `/login`, which on a page that can never recognise anyone
would close a loop with no way in, and not at the gate's own URL, which would
work and would wire Borant ID into an app that must keep running without it.

**The role hint is honoured.** The gate can suggest `basic`, `standard`,
`full`, `teacher` or `admin`, and the app applies it when it creates a profile.
All of them except `basic` carry the `pipeline` permission, which spends on the
server's Anthropic key — so a profile created that way is logged loudly, and
given the default monthly ceiling (`ARGUMAP_DEFAULT_BUDGET_USD`, 200). An
unrecognised hint is treated as a typo and falls back to `basic`.

**A page that needs an identity fails closed.** In `gateway` an unauthenticated
request does *not* redirect to `/login` — the app switches that route off in
this mode and sends it back, so the two would bounce forever. Production never
shows it because the gate intercepts first, but a wrong proxy matcher would
produce a spin instead of an error, and a loop is far harder to diagnose than a
status code. The answer is a 503 naming what the operator should check, because
a request arriving with no identity means the gate did not run.
