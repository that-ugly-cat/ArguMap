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
| `PROVISION_SECRET` | No | Shared secret for `/internal/provision`. Unset = the route does not exist. |
| `PROVISION_TRUSTED` | No | CIDR the gate calls from, e.g. `172.28.0.0/16`. Unset = the route does not exist. |

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

**Two switches, not one.** The role says whether an account may teach; the
`course_teachers` junction says which courses. Both are required, and they are
set in different places, so an account can sit in `course_teachers` with the
`full` role and get 403 everywhere that matters — the state Nikola, Anna and
Enrico were in until 8 Sep 2026. `teacher` is exactly `full` plus
`view_course_maps`, which spends nothing: `pipeline` and `debate` are the two
that touch the API key and `full` already holds both.

Loosening the code instead of promoting the role does not work as a half
measure. `_may_admin_map` is the last of a series: the course page,
`/api/courses/{id}/maps`, `/api/courses` and the template editor all gate on
`view_course_maps` on their own, so an account without it could at best open a
student map from a link it has no way to obtain.

**Who may open a map** — one rule, `_may_admin_map()`, used by `get_map`,
`update_map`, `open_map`, `_map_annot_admin` and `debate` (it was six divergent
copies until 8 Sep 2026, and `admin` was missing from all of them):

- the owner, always;
- on someone else's map: a teacher of the course it is assigned to, or an admin;
- **a map with no course is visible to its owner alone, admins included.**

That last line is load-bearing. Assignment to a course *is* the hand-in, and as
of 8 Sep 2026 nothing assigns it automatically — saving a map used to file it
into the author's course whenever they belonged to exactly one, with the course
selector hidden in precisely that case. Now the selector is shown from one
course up and starts on "no course"; templates still assign their own course,
which is what an assignment is.

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
`pipeline` permission. Promotion stays a human click in `/admin`.

`_check_budget` returns immediately when `monthly_budget_usd` is NULL, so an
account with no ceiling is an account with no brake. That used to be every
account; as of 8 Sep 2026 all twelve carry one, at $200. Check before assuming
either way — `SELECT count(*) FROM users WHERE monthly_budget_usd IS NULL`.

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

**The code is minted in two places, and backfilled once.** Originally only
`POST /annotate/open` minted it — which a map whose layer was *already* open
before 24 Aug 2026 never passes through again. Those maps showed the sharing
link, no code and no QR, and since the layer reads as open the panel offers only
`Close`: the code could not be obtained at all. Mostly the students' course
maps, which is why it looked like a permissions problem. Fixed on 8 Sep 2026 in
two layers: an additive migration in `init_db()` gives a code to every map with
an `annotate_token` and no `join_code` (3 of 6 on production), and `open_map`
mints one on sight for anyone who may administer the layer. A map that never had
an annotation layer stays without a code — the code is born with the layer, and
minting unused ones would only widen what is there to guess.

Codes are six digits where RoomPulse uses five. In a session where both tools
are on the slides, a code typed into the wrong app fails on its length before
any lookup, instead of quietly resolving onto someone else's map.

Failed lookups are counted per client IP: past 30 in a minute the route sleeps
a second before answering, past 200 it returns 429. The soft step is
deliberate — a lecture hall is one NATed address, so a hard block after a few
dozen collective typos would lock out the students who typed correctly.

## The viewer does its own zoom, on purpose

X6's `mousewheel` widget is switched off in `automap_v2_x6.py`. It reads only
the *sign* of `deltaY` and applies a fixed step once per animation frame, which
is one step for a mouse notch and thirty to a hundred for a Mac trackpad swipe
— the gesture plus its inertia — so the map slammed into `minScale` or
`maxScale` before the hand stopped moving. The replacement scales by the delta
(`exp(-dy * k)`, `k` tuned so a 100px notch still lands on the old 1.1x).

Safari never turns a trackpad pinch into a `ctrl`+wheel event the way Chrome and
Firefox do; it fires `gesturestart`/`gesturechange`/`gestureend` with a
cumulative scale. Those are handled too, **scoped to the canvas** so a pinch over
the side panels still zooms the page and Safari's own accessibility zoom
survives. If either handler is ever removed, Mac users lose zoom and nobody else
notices — which is exactly how this went unreported for months.

`addNode` places new nodes in the *visible* area, cascading off what is already
there. It used to use the fixed graph point `{80, 80}`: invisible as soon as the
canvas was panned, and identical for every node, so the second one hid under the
first — in the saved `_layout` as well as on screen.

## Provisioning in advance (`/internal/provision`)

Optional, off unless both variables are set. Without it a profile — and its
welcome map — is born the first time somebody opens ArguMap. With it, Borant ID
says who is coming as soon as it grants access, so a class exists here the
evening before and can be put into courses before the first lecture instead of
during it.

**Not reachable from the internet, by construction.** The route is not in the
Caddy config at all: the gate calls the container directly over a docker network
the two share. Two locks, and missing either makes the route answer 404 as
though it were not there — `PROVISION_SECRET` (the credential, compared in
constant time) and `PROVISION_TRUSTED` (the CIDR the gate's container is on).

Wiring:

```bash
docker network create borant_provision
docker network inspect borant_provision -f '{{(index .IPAM.Config 0).Subnet}}'
```

Read that subnet off the command, do not guess it: `172.17.0.0/16` is the
*default bridge* and not this network. Put it in `PROVISION_TRUSTED`, join both
compose files to the network (`networks: [default, borant_provision]` on the
service, `external: true` on the network), set the secret, and restart.

**And widen `BORANT_TRUSTED_PROXY` in the same breath.** A second network
changes which gateway the proxy's requests appear to come from: docker picks
among them in alphabetical order of network name, so whether it changes for a
given app is decided by its project name. ArguMap got lucky — `argumap_default`
sorts ahead of `borant_provision` and nothing moved — while RoomPulse did not,
and locked everyone out until the list was widened (8 Sep 2026). Luck is not a
configuration:

```
BORANT_TRUSTED_PROXY=172.20.0.1,192.168.240.1
```

Then in the gate's `/admin/apps` → ArguMap fill in the same secret and

```
http://argumap:8000/internal/provision
```

— the container's own name and the port it listens on **inside** the container,
which is 8000 and not the 8012 published on the host. «Resync» there pushes
everyone who already has a grant, and the numbers it prints are the proof the
wiring works.

**It creates and nothing else.** No profile updated, no role changed, nothing
deactivated: a stolen secret buys empty accounts, not somebody's maps. And it
does **not** link by address — an incoming address already held by an unlinked
local row comes back as a conflict, untouched, for `map_borant.py` to resolve by
hand. That matters more here than anywhere: in this app one person legitimately
holds several rows under different addresses, so guessing would be wrong more
often than elsewhere.

**A pushed profile gets the welcome map**, because both roads go through the
same `provision()`. That is rule 4 of the perimeter's checklist, and it was
written after this very app opened empty for profiles born at the gate.

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

## Normative before empirical, everywhere

Every list of node types in the app puts the normative premise ahead of the
empirical one: the add panel, the legend, the edit-node select, the help modal,
the pipeline's system prompt and ID conventions, the text export. Since
9 Sep 2026 the guided picker, its progress chips, the template editor's fields
and `_template_seed` do too — they were the last four holdouts, and they were
the ones a teacher actually sees, which is how Holger noticed.

The reason is the shape of an ethical argument as it is usually built: a
principle first, then the fact that engages it. `_template_seed`'s order is not
cosmetic — it reaches dagre as the `nodes` array and decides which seeded
premise sits left of which on the student's canvas.

**Presentation only.** The guided mode imposes no sequence: any support type
may be added at any point, and `_guidedUnlockReady()` is a conjunction, not a
path. Turning the order into a *constraint* was considered and rejected — plenty
of arguments start from the datum and let the norm qualify it, and forcing the
other way would have meant a state machine that still has to let intermediate
conclusions, metaphysical commitments and objections through at any moment.

## The legend has two homes, and the canvas is not one of them by default

The legend used to be a white box floating over the bottom-left of the canvas in
every mode. It is now docked at the bottom of the left column, where there was
already room, and the canvas is left to the map.

It still floats — same box, same place — in exactly the situations where that
column is not on screen: `body.guided`, `body.annotate`, `body.left-hidden` (the
collapse toggle sets it), and under the 820px media query. Miss any one of those
and a whole class of users loses the only colour key they have: annotators on a
share link never see the left column at all, and neither does anyone on a phone.

Both hosts — `#legend-dock` and `#legend-float` — are filled by `renderLegend()`
from `NODE_COLORS`/`EDGE_COLORS` and `TYPE_LABELS`, so the two copies cannot
drift and the hex values are no longer written out a third time.

## Seeded template premises: connected or loose

`templates.seed_connected` (BOOLEAN DEFAULT 1, additive migration) decides what a
`*` premise arrives as on the student's map. On — the default, and what every
template did before the column existed — they land already supporting the claim,
under a ∧ joiner when there are several. Off, they land as loose nodes and
drawing the inferential links is the exercise.

Two things not to get wrong when touching this:

- **Test it with `is not False`, never for truthiness.** Rows written before the
  migration read back as NULL, and those templates were seeded connected. A plain
  `if tmpl.seed_connected:` would silently unwire every template authored before
  9 Sep 2026. The client does the same with `!== false`.
- **Seeded objections stay unconnected in both modes.** That is not an oversight
  the flag forgot to cover: an objection's real target is ambiguous — the claim,
  a premise, an inference — so it is wired by hand, as it always was.

`push_template` carries the flag to the copy; `_map_is_pristine` is unaffected,
since a seeded map already had more than one node either way.
