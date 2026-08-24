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

A reverse proxy has two branches, gated and public, and neither fits. Put those
five on the **public** branch and the identity headers get stripped, so the
owner becomes anonymous to them — `_can_read_annotations` then refuses once the
session is closed, which is exactly when a teacher reads the annotations, and
moderation through `_own_annotation` stops working too. Put them on the
**gated** branch and anonymous annotation stops working at all.

So this app cannot simply be gated per-path like the others. The clean fix is
to split the API by audience — give the anonymous annotator its own prefix, and
leave `/api/maps/...` gated — which is an app change plus a change in the
annotation client, not a proxy rule. Until that is done, `AUTH_MODE=gateway`
should not be switched on here.
