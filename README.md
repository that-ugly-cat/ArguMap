# ArguMap

Web app for **argument mapping** with explicit inferential structure, built for
teaching applied ethics (bioethics in particular). Maps an argument as a graph of
typed nodes (claim, empirical/normative premises, metaphysical commitments,
intermediate conclusions) connected by inferential steps that carry a relation
(supports / attacks / qualifies), a validity judgement, and optional bias /
fallacy annotations.

FastAPI + SQLite + Jinja2, served as a single Docker container. UI in **EN / IT / DE**.

## Three ways to build a map

- **Analyse a text** — paste a text and an LLM pipeline extracts the argument map.
- **Guided construction** — start from a claim and answer prompts that walk you
  down to its premises; each node type comes with a short explanation and example.
  Free editing unlocks once the map holds at least one empirical and one normative
  premise. *(Top-down for now; bottom-up is planned.)*
- **Empty map** — build manually on a blank canvas (X6 editor, full annotations).

Plus a **Debate-A-Bot** that argues for or against a saved map.

## Quick start (Docker)

```bash
cp .env.example .env      # then fill in ANTHROPIC_API_KEY and JWT_SECRET
docker compose up -d --build
```

The app listens on `127.0.0.1:8000` (put a reverse proxy in front for HTTPS).

## Configuration

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | yes | LLM pipeline + Debate-A-Bot |
| `JWT_SECRET` | yes | Signs session tokens. Random, min 32 chars. |

See [DEPLOY.md](DEPLOY.md) for full server setup (admin bootstrap, Caddy, updates).

## Notes

- The logos in `imgs/` still carry the previous "AutoMap" wordmark — replace with
  ArguMap assets when available; the template references use the existing filenames.
