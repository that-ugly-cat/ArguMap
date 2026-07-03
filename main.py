"""
AutoMap v2 — FastAPI application.

Architecture notes:
- Auth: JWT in httpOnly cookie; see auth.py.
- DB: SQLite via SQLAlchemy ORM; see models.py. Single writer, WAL not enabled.
- Map viewer: generate_html_x6() produces a self-contained HTML page; _inject_web_ui()
  appends backend-aware JS (save, share, debate) into that page at serve time.
  This keeps the visualizer decoupled from the backend while allowing per-user UI.
- Pipeline: Anthropic SDK is synchronous. The streaming endpoint bridges it to FastAPI's
  async event loop via threading.Thread + queue.Queue (see run_pipeline_stream).
- Budget: per-user monthly spend is checked before pipeline and debate calls only.
  File extraction (/api/extract_text) is not budget-gated (no LLM call).
- Share tokens: generated lazily on first POST /api/maps/{id}/share (idempotent).
  Revoked by setting share_token=None. Public route /share/{token} requires no login.
"""
import json
import secrets
import markdown as _markdown
import anthropic as _anthropic
from pathlib import Path

_DOCS_DIR = Path(__file__).parent / "docs"

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm.attributes import flag_modified
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

import locales as _locales

from auth import (
    create_token, get_current_user, get_user_or_none, hash_password,
    require_permission, verify_password,
)
from models import (
    Annotation, AnnotationSession, Course, Map, Role, Template, UsageLog, User,
    course_teachers,
    get_db, init_db, log_usage, user_month_cost,
)
from automap_v2_pipeline import extract_map, ingest_bytes
from automap_v2_x6 import generate_html_x6

app = FastAPI(title="AutoMap v2")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/imgs",   StaticFiles(directory="imgs"),   name="imgs")
templates = Jinja2Templates(directory="templates")


def _get_lang(request: Request) -> str:
    code = request.cookies.get("lang", _locales.DEFAULT)
    return code if code in _locales.SUPPORTED else _locales.DEFAULT


_GUIDE_TITLES = {
    "user-guide":    "User Guide",
    "teacher-guide": "Teacher Guide",
    "admin-guide":   "Admin Guide",
}

@app.get("/docs/{guide}", response_class=HTMLResponse)
def docs_page(guide: str, request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if guide not in _GUIDE_TITLES:
        raise HTTPException(404, "Guide not found")
    user = get_user_or_none(session, db)
    lang = _get_lang(request)
    path = _DOCS_DIR / lang / f"{guide}.md"
    if not path.exists():
        path = _DOCS_DIR / "en" / f"{guide}.md"
    if not path.exists():
        raise HTTPException(404, "Guide not found")
    md_text = path.read_text(encoding="utf-8")
    # For placeholder files (IT/DE), append the EN content
    en_path = _DOCS_DIR / "en" / f"{guide}.md"
    if path != en_path and en_path.exists() and len(md_text.strip()) < 200:
        md_text += "\n\n" + en_path.read_text(encoding="utf-8")
    content = _markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    t = _locales.get_t(lang)
    return templates.TemplateResponse("docs.html", {
        "request": request,
        "title":   _GUIDE_TITLES[guide],
        "content": content,
        "t":       t,
        "lang":    lang,
    })


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    next_url = request.query_params.get("next", "/app")
    lang = code if code in _locales.SUPPORTED else _locales.DEFAULT
    resp = RedirectResponse(next_url, status_code=302)
    resp.set_cookie("lang", lang, max_age=365 * 24 * 3600, samesite="lax")
    return resp


@app.on_event("startup")
def startup():
    init_db()


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        lang = _get_lang(request)
        return templates.TemplateResponse("403.html", {"request": request, "t": _locales.get_t(lang), "lang": lang}, status_code=403)
    return await http_exception_handler(request, exc)


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    from auth import _decode_token
    token = request.cookies.get("session")
    if token:
        try:
            user_id = _decode_token(token)
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
            if user:
                return RedirectResponse("/app")
        except Exception:
            pass
    lang = _get_lang(request)
    return templates.TemplateResponse("login.html", {"request": request, "t": _locales.get_t(lang), "lang": lang})


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        lang = _get_lang(request)
        t    = _locales.get_t(lang)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "t": t, "lang": lang, "error": t['login_wrong_pw']},
            status_code=401,
        )
    token = create_token(user.id)
    resp = RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("session")
    return resp


# ── App ───────────────────────────────────────────────────────────────────────

@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    lang = _get_lang(request)
    return templates.TemplateResponse("index.html", {
        "request":      request,
        "user":         user,
        "can_pipeline":        user.has_permission("pipeline"),
        "can_debate":          user.has_permission("debate"),
        "can_admin":           user.has_permission("admin"),
        "can_manage_courses":  user.has_permission("view_course_maps"),
        "t":            _locales.get_t(lang),
        "lang":         lang,
    })


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _check_budget(user: User, db):
    if user.monthly_budget_usd is None:
        return
    spent = user_month_cost(db, user.id)
    if spent >= user.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget exceeded (${spent:.4f} / ${user.monthly_budget_usd:.2f})"
        )


@app.post("/api/pipeline")
async def run_pipeline(
    request: Request,
    user: User = Depends(require_permission("pipeline")),
    db: Session = Depends(get_db),
):
    body = await request.json()
    text     = body.get("text", "").strip()
    map_id   = body.get("map_id", "map")
    title    = body.get("title", "Argument Map")
    model    = body.get("model", "claude-sonnet-4-6")

    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    _check_budget(user, db)

    reasoning_log = []

    def on_step(name, reasoning):
        reasoning_log.append({"step": name, "reasoning": reasoning})

    result = extract_map(text, map_id, title, model=model, on_step=on_step)
    log_usage(db, user_id=user.id, feature="pipeline", model=result.usage["model"],
              tokens_in=result.usage["input_tokens"], tokens_out=result.usage["output_tokens"])
    return {"map": result.to_dict(), "reasoning": reasoning_log}


@app.post("/api/pipeline/stream")
async def run_pipeline_stream(
    request: Request,
    user: User = Depends(require_permission("pipeline")),
    db: Session = Depends(get_db),
):
    body = await request.json()
    text   = body.get("text", "").strip()
    map_id = body.get("map_id", "map")
    title  = body.get("title", "Argument Map")
    model  = body.get("model", "claude-sonnet-4-6")

    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    _check_budget(user, db)

    import asyncio
    import queue

    q: queue.Queue = queue.Queue()

    def on_step(name, reasoning):
        q.put({"step": name, "reasoning": reasoning})

    def run():
        try:
            result = extract_map(text, map_id, title, model=model, on_step=on_step)
            log_usage(db, user_id=user.id, feature="pipeline", model=result.usage["model"],
                      tokens_in=result.usage["input_tokens"], tokens_out=result.usage["output_tokens"])
            q.put({"done": True, "map": result.to_dict()})
        except Exception as e:
            q.put({"error": str(e)})

    # The Anthropic SDK is synchronous; run it in a daemon thread and relay
    # results to the async event loop via a queue. daemon=True ensures the thread
    # doesn't prevent process shutdown if the client disconnects mid-stream.
    import threading
    threading.Thread(target=run, daemon=True).start()

    async def event_stream():
        loop = asyncio.get_event_loop()
        while True:
            try:
                msg = await loop.run_in_executor(None, lambda: q.get(timeout=120))
                yield f"data: {json.dumps(msg)}\n\n"
                if "done" in msg or "error" in msg:
                    break
            except Exception:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── File extraction ───────────────────────────────────────────────────────────

@app.post("/api/extract_text")
async def extract_text(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("pipeline")),
):
    content = await file.read()
    try:
        text = ingest_bytes(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"text": text, "filename": file.filename}


# ── Maps ──────────────────────────────────────────────────────────────────────

class MapSave(BaseModel):
    title:       str
    map_data:    dict
    course_id:   int | None = None
    reasoning:   list | None = None
    source_text: str | None = None


@app.get("/api/maps")
def list_maps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    maps = db.query(Map).filter(Map.user_id == user.id).order_by(Map.updated_at.desc()).all()
    return [{"id": m.id, "title": m.title, "course_id": m.course_id,
             "has_reasoning":   m.reasoning is not None,
             "has_source_text": m.source_text is not None,
             "created_at": m.created_at, "updated_at": m.updated_at} for m in maps]


@app.post("/api/maps")
def save_map(body: MapSave, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = Map(user_id=user.id, title=body.title, map_data=body.map_data,
            course_id=body.course_id, reasoning=body.reasoning,
            source_text=body.source_text)
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"id": m.id}


@app.get("/api/maps/{map_id}/source_text")
def get_source_text(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if not m.source_text:
        raise HTTPException(404, "No source text stored for this map")
    return {"text": m.source_text}


@app.get("/api/maps/{map_id}/reasoning")
def get_reasoning(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if not m.reasoning:
        raise HTTPException(404, "No reasoning stored for this map")
    return m.reasoning


@app.get("/api/maps/{map_id}")
def get_map(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    # teacher can see maps from their courses; students only own maps
    if m.user_id != user.id:
        if not user.has_permission("view_course_maps"):
            raise HTTPException(403, "Forbidden")
        course = db.query(Course).filter(Course.id == m.course_id).first()
        if not course or not any(t.id == user.id for t in course.teachers):
            raise HTTPException(403, "Forbidden")
    return m.map_data


@app.put("/api/maps/{map_id}")
def update_map(map_id: int, body: MapSave, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    m.title    = body.title
    m.map_data = body.map_data
    # SQLAlchemy does not track in-place mutations on JSON columns.
    # flag_modified() forces the ORM to mark the column dirty so the UPDATE is emitted.
    flag_modified(m, 'map_data')
    db.commit()
    return {"ok": True}


class CourseAssign(BaseModel):
    course_id: int | None = None

@app.patch("/api/maps/{map_id}/course")
def assign_course(map_id: int, body: CourseAssign, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    m.course_id = body.course_id
    db.commit()
    return {"ok": True}


@app.delete("/api/maps/{map_id}")
def delete_map(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ── Guided templates (teacher-authored scaffolds) ─────────────────────────────

class TemplateCreate(BaseModel):
    title:     str
    claim:     str
    course_id: int | None = None
    slots:     dict | None = None


def _require_teacher(user: User):
    # 'view_course_maps' is the teacher gate (teachers + admin hold it).
    if not user.has_permission("view_course_maps"):
        raise HTTPException(403, "Teacher access required")


@app.get("/api/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_teacher(user)
    q = db.query(Template).filter(Template.teacher_id == user.id).order_by(Template.created_at.desc())
    return [{"id": t.id, "title": t.title, "claim": t.claim, "course_id": t.course_id,
             "slots": t.slots, "created_at": t.created_at} for t in q.all()]


@app.post("/api/templates")
def create_template(body: TemplateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_teacher(user)
    if not body.title.strip() or not body.claim.strip():
        raise HTTPException(400, "Title and claim are required")
    t = Template(teacher_id=user.id, title=body.title.strip(), claim=body.claim.strip(),
                 course_id=body.course_id, slots=body.slots)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id}


@app.patch("/api/templates/{template_id}")
def update_template(template_id: int, body: TemplateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_teacher(user)
    t = db.query(Template).filter(Template.id == template_id, Template.teacher_id == user.id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    if not body.title.strip() or not body.claim.strip():
        raise HTTPException(400, "Title and claim are required")
    # Edits affect maps opened from now on; already-created student instances keep
    # the seed they were given (they are independent copies).
    t.title     = body.title.strip()
    t.claim     = body.claim.strip()
    t.course_id = body.course_id
    t.slots     = body.slots
    db.commit()
    return {"id": t.id}


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = db.query(Template).filter(Template.id == template_id, Template.teacher_id == user.id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    db.commit()
    return {"ok": True}


def _is_teacher_or_admin(u: User) -> bool:
    return u.has_permission("view_course_maps") or u.has_permission("admin")


@app.get("/api/teachers")
def list_teachers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Teachers/admins a template can be pushed to."""
    _require_teacher(user)
    out = []
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        if u.id != user.id and _is_teacher_or_admin(u):
            out.append({"id": u.id, "name": u.name or u.email, "email": u.email})
    return out


class TemplatePush(BaseModel):
    user_id: int


@app.post("/api/templates/{template_id}/push")
def push_template(template_id: int, body: TemplatePush, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Give another teacher/admin their own copy of this template."""
    _require_teacher(user)
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    if t.teacher_id != user.id and not user.has_permission("admin"):
        raise HTTPException(403, "Forbidden")
    recip = db.query(User).filter(User.id == body.user_id).first()
    if not recip or not _is_teacher_or_admin(recip):
        raise HTTPException(400, "Recipient must be a teacher or admin")
    copy = Template(teacher_id=recip.id, title=t.title, claim=t.claim, slots=t.slots, course_id=None)
    db.add(copy)
    db.commit()
    return {"ok": True}


@app.get("/t/{template_id}")
def open_template(template_id: int, request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    """Student entry point. Get-or-create the caller's Map instance for this
    template (idempotent on user+template), then open it in guided mode."""
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse(f"/login?next=/t/{template_id}", status_code=302)
    tmpl = db.query(Template).filter(Template.id == template_id).first()
    if not tmpl:
        raise HTTPException(404, "Template not found")
    seed = _template_seed(tmpl)
    m = db.query(Map).filter(Map.user_id == user.id, Map.template_id == tmpl.id).first()
    if not m:
        m = Map(user_id=user.id, title=tmpl.title, map_data=seed,
                course_id=tmpl.course_id, template_id=tmpl.id)
        db.add(m)
        db.commit()
        db.refresh(m)
    elif _map_is_pristine(m):
        # The student never touched this map (only the claim, no work): re-apply the
        # current seed, so a template opened before its `*` premises existed catches up.
        m.map_data = seed
        flag_modified(m, "map_data")
        db.commit()
    return RedirectResponse(f"/map/{m.id}?mode=guided", status_code=302)


def _template_seed(tmpl: Template) -> dict:
    """Build the initial map_data for a template: claim + `*`-seeded premises
    (co-dependent under a ∧ joiner) + `*`-seeded objections (attacking the claim)."""
    nodes = [{"id": "C1", "type": "claim", "content": tmpl.claim, "notes": ""}]
    steps: list = []
    slots = tmpl.slots or {}
    support_ids = []
    for ntype, pfx in (("empirical_premise", "E"), ("normative_premise", "N")):
        for i, txt in enumerate((slots.get(ntype) or {}).get("seed", []), 1):
            nid = f"{pfx}{i}"
            nodes.append({"id": nid, "type": ntype, "content": txt, "notes": ""})
            support_ids.append(nid)
    if support_ids:
        steps.append({"id": f"S{len(steps) + 1}", "sources": support_ids, "target": "C1",
                      "linked": len(support_ids) > 1, "relation": "supports"})
    # Objections are seeded unconnected — their real target is ambiguous, so the
    # student/teacher wires them by hand in edit mode.
    for i, txt in enumerate((slots.get("objection") or {}).get("seed", []), 1):
        nodes.append({"id": f"O{i}", "type": "objection", "content": txt, "notes": ""})
    return {"title": tmpl.title, "nodes": nodes, "steps": steps}


def _map_is_pristine(m: Map) -> bool:
    data = m.map_data or {}
    return len(data.get("nodes", [])) <= 1 and not data.get("steps")


@app.get("/teacher/templates", response_class=HTMLResponse)
def teacher_templates_page(request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    lang = _get_lang(request)
    if not user.has_permission("view_course_maps"):
        return templates.TemplateResponse("403.html", {"request": request, "t": _locales.get_t(lang), "lang": lang}, status_code=403)
    return templates.TemplateResponse("templates.html", {
        "request": request, "user": user, "t": _locales.get_t(lang), "lang": lang,
    })


# ── Map viewer ───────────────────────────────────────────────────────────────

_ANNOT_CSS = """
#annot-panel{position:fixed;top:44px;right:0;width:320px;bottom:0;z-index:400;background:#f7fafc;border-left:1px solid #dde1e7;display:none;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
body.annot-open #annot-panel{display:flex}
#annot-head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #dde1e7;background:#fff}
#annot-head span{font-size:13px;font-weight:700;color:#1a202c}
#annot-x{background:none;border:none;font-size:14px;color:#718096;cursor:pointer}
#annot-body{padding:14px;overflow-y:auto;flex:1;font-size:12px;color:#2d3748}
#annot-thread{border-top:2px solid #dde1e7;margin-top:12px;padding-top:10px;font-size:12px;color:#2d3748}
#annot-share{background:#ebf5fb;border:1px solid #bee3f8;border-radius:6px;padding:10px;margin-bottom:12px;font-size:12px}
.annot-cat-item{font-size:11px;line-height:1.4;padding:5px 0;border-top:1px solid #edf2f7}
#annot-cat-view{margin-top:8px}
.annot-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#718096;font-weight:700;margin:10px 0 4px}
.annot-target{background:#ebf5fb;border:1px solid #bee3f8;border-radius:6px;padding:8px 10px;margin-bottom:10px}
.annot-tk{font-size:9px;text-transform:uppercase;color:#2980b9;font-weight:700;display:block;margin-bottom:2px}
.annot-plaus{display:flex;gap:6px;margin-bottom:10px}
.annot-p{flex:1;padding:6px 0;border:1px solid #cbd5e0;border-radius:5px;background:#fff;cursor:pointer;font-weight:600;color:#4a5568}
.annot-p.on{background:#2980b9;color:#fff;border-color:#2980b9}
#annot-body textarea,#annot-body input[type=text],#annot-thread textarea,#annot-thread input[type=text],.annot-link{width:100%;padding:7px 9px;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;font-family:inherit;background:#fff;margin-bottom:6px}
.annot-add{width:100%;padding:8px;border:none;border-radius:6px;background:#2980b9;color:#fff;font-weight:600;cursor:pointer;font-size:12px;margin-bottom:8px}
.annot-flags{display:flex;gap:6px;align-items:center;margin-bottom:8px}
.annot-flags input{flex:1;margin-bottom:0}
.annot-mini{padding:6px 9px;border:1px solid #cbd5e0;border-radius:5px;background:#fff;cursor:pointer;font-size:11px;color:#4a5568;white-space:nowrap}
.annot-danger{color:#c53030;border-color:#feb2b2;margin-top:6px;width:100%}
.annot-list{margin-top:6px}
.annot-item{border-top:1px solid #edf2f7;padding:7px 0}
.annot-au{font-size:10px;color:#718096;font-weight:600}
.annot-tx{font-size:12px;color:#2d3748;margin:2px 0}
.annot-del{background:none;border:none;color:#c53030;font-size:10px;cursor:pointer;padding:0}
.annot-empty,.annot-note{color:#718096;font-size:11px;padding:6px 0}
.annot-hint{font-size:10px;color:#718096;margin:6px 0 4px}
.annot-status{font-size:11px;color:#2d3748;margin-bottom:6px}
.annot-linkbtn{background:none;border:none;color:#2980b9;font-size:11px;cursor:pointer;padding:0;margin-bottom:8px}
.annot-hr{border:none;border-top:1px solid #dde1e7;margin:12px 0}
"""

# Backend-aware annotation client. Uses the viewer globals `graph` and `setMode`.
# All map/edge writes go through the annotations API; realtime is 2s polling.
_ANNOT_JS = r"""
(function(){
  if(!window.ANNOT || !ANNOT.mapId) return;
  var T=ANNOT.t||{};
  function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function escA(s){return esc(s).replace(/"/g,'&quot;');}
  var store={open:!!ANNOT.canWrite,annotations:[],aggregates:{}};
  var sel=null, timer=null, layerOn=false, _lastMapUp=null, _saveTimer=null;
  var ownerMode = ANNOT.canAdmin && !ANNOT.auto;   // owner/teacher on /map/{id}: edit + annotate coexist
  var studentMode = !ownerMode;                    // /annotate/{token}: annotate-only, structure locked
  var panel=document.getElementById('annot-panel');
  var body=document.getElementById('annot-body');
  var titleEl=document.getElementById('annot-title');
  if(titleEl) titleEl.textContent=T.annot_title;
  var btn=document.getElementById('btn-annotate');
  function api(p,o){o=o||{};o.headers=Object.assign({'Content-Type':'application/json'},o.headers||{});return fetch(p,o);}
  // Catalog of fallacy/bias names from the viewer's SCHEMES_DATA (shared global lexical scope).
  function catNames(kind){var out=[];try{var root=(typeof SCHEMES_DATA!=='undefined'?SCHEMES_DATA:{})[kind]||{};Object.keys(root).forEach(function(fk){((root[fk]||{})[kind]||[]).forEach(function(it){if(it&&it.name)out.push(it.name);});});}catch(e){}return out;}
  function ensureDatalist(){[['fallacies','annot-fallacies-list'],['biases','annot-biases-list']].forEach(function(p){if(document.getElementById(p[1]))return;var dl=document.createElement('datalist');dl.id=p[1];catNames(p[0]).forEach(function(n){var o=document.createElement('option');o.value=n;dl.appendChild(o);});document.body.appendChild(dl);});}
  function selFromCell(cell){var kind=(cell.isEdge&&cell.isEdge())?'edge':'node';var d=(cell.getData&&cell.getData())||{};sel={kind:kind,id:cell.id,label:d.content||(kind==='edge'?(T.annot_target_edge||'Step'):cell.id)};}
  // Viewers can't drag nodes/edges (set the option directly and via the API).
  function _lockViewer(){ if(typeof graph==='undefined')return; try{ graph.options.interacting={nodeMovable:false,edgeMovable:false,magnetConnectable:false}; if(graph.setInteracting)graph.setInteracting({nodeMovable:false,edgeMovable:false,magnetConnectable:false}); }catch(e){} }
  function enter(){layerOn=true;if(btn)btn.textContent=T.annot_exit;ensureDatalist();
    if(studentMode){document.body.classList.add('annot-open');if(window.setMode)setMode('annotate');_lockViewer();}
    else{document.body.classList.add('annot-on');renderShare();}
    startPoll();drawLayer();renderThread();}
  function leave(){layerOn=false;if(btn)btn.textContent=T.annot_enter;sel=null;stopPoll();
    document.querySelectorAll('.annot-viz').forEach(function(e){e.remove();});
    if(studentMode){document.body.classList.remove('annot-open');if(window.setMode)setMode('select');}
    else{document.body.classList.remove('annot-on');var e=document.getElementById('annot-thread');if(e)e.remove();var sh=document.getElementById('annot-share');if(sh)sh.remove();}}
  window.__annotToggle=function(){layerOn?leave():enter();};
  window.__annotClosePanel=function(){leave();};
  window.__annotBack=function(){sel=null;renderThread();};
  window.__annotateClick=function(cell){if(!layerOn||!studentMode)return;selFromCell(cell);renderThread();};
  if(ownerMode){
    graph.on('node:click',function(a){if(!layerOn)return;selFromCell(a.node);renderThread();});
    graph.on('edge:click',function(a){if(!layerOn)return;selFromCell(a.edge);renderThread();});
    graph.on('blank:click',function(){sel=null;renderThread();});
  }
  if(ownerMode && ANNOT.owner && typeof graph!=='undefined'){
    ['node:added','node:removed','node:moved','edge:added','edge:removed','node:change:data','edge:change:data','cell:change:position'].forEach(function(ev){
      graph.on(ev, function(){ if(layerOn) _annotAutosave(); });
    });
  }
  function startPoll(){poll();timer=setInterval(poll,2000);}
  function stopPoll(){if(timer)clearInterval(timer);timer=null;}
  function typingInAnnot(){var el=document.activeElement;if(!el||!el.closest)return false;return !!(el.closest('#annot-thread,#annot-panel,#annot-share')&&(el.tagName==='TEXTAREA'||el.tagName==='INPUT'));}
  // Only refresh the thread on poll when a cell is selected — otherwise we would
  // clobber the home view / open catalog every 2s.
  // Viewers pick up the owner's live map edits: when the map's timestamp changes,
  // refetch the structure and rebuild (the owner is the source, so they don't).
  async function _refreshMapIfChanged(){
    if(ownerMode || ANNOT.owner || !store.map_updated) return;   // the owner is the source, never rebuild
    if(_lastMapUp === null){ _lastMapUp = store.map_updated; return; }
    if(store.map_updated === _lastMapUp) return;
    _lastMapUp = store.map_updated;
    try{var dr=await api('/api/maps/'+ANNOT.mapId+'/annotate/data');if(!dr.ok)return;var dj=await dr.json();
      if(dj.map_data && typeof rebuildFromMap==='function'){ rebuildFromMap(dj.map_data); _lockViewer(); }}catch(e){}
  }
  async function poll(){try{var r=await api('/api/maps/'+ANNOT.mapId+'/annotations');if(!r.ok)return;store=await r.json();await _refreshMapIfChanged();drawLayer();if(layerOn&&sel&&!typingInAnnot())renderThread();}catch(e){}}
  // Owner autosave while annotating, so viewers see edits within a poll cycle.
  function _annotAutosave(){
    if(!ANNOT.owner) return;
    if(_saveTimer) clearTimeout(_saveTimer);
    _saveTimer=setTimeout(async function(){
      try{ if(typeof _captureState!=='function') return; var st=_captureState(); if(!st) return;
        await api('/api/maps/'+ANNOT.mapId,{method:'PUT',body:JSON.stringify({title:st.title||'Argument Map',map_data:st})}); }catch(e){}
    },800);
  }
  function plausColor(v){if(v==null)return '#a0aec0';var p=(v-1)/4;var r=Math.round(210*(1-p)+56*p),g=Math.round(64*(1-p)+161*p);return 'rgb('+r+','+g+',72)';}
  function svgEl(tag,attrs){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(var k in attrs)e.setAttribute(k,attrs[k]);return e;}
  function labelsFor(tk,tid,kind){return store.annotations.filter(function(a){return a.target_kind===tk&&a.target_id===tid&&a.kind===kind;}).map(function(a){return (a.payload&&a.payload.label)||'';}).filter(Boolean);}
  // Compact SVG marker: distribution bar (1-5) + comment count + fallacy/bias chips.
  function makeMarker(d,fall,bias){
    var g=svgEl('g',{'class':'annot-viz','pointer-events':'none'});
    var dist=d.plaus_dist||[0,0,0,0,0];var total=dist.reduce(function(a,b){return a+b;},0);var x=0;
    if(total>0){
      var mx=Math.max.apply(null,dist);
      for(var v=0;v<5;v++){var h=mx?Math.max(2,Math.round(dist[v]/mx*15)):2;
        g.appendChild(svgEl('rect',{x:v*10,y:16-h,width:9,height:h,rx:1,fill:plausColor(v+1),opacity:dist[v]?0.95:0.28}));}
      if(d.plaus_mean!=null){var tx=(d.plaus_mean-1)/4*49;g.appendChild(svgEl('line',{x1:tx,y1:16,x2:tx,y2:20,stroke:'#1a202c','stroke-width':2}));}
      x=54;
    }
    if(d.comments>0){var ct=svgEl('text',{x:x,y:13,'font-size':11,fill:'#2d3748'});ct.textContent='💬'+d.comments;g.appendChild(ct);}
    var chips=[];fall.forEach(function(l){chips.push({t:'⚠ '+l,c:'#dd6b20'});});bias.forEach(function(l){chips.push({t:'⚠ '+l,c:'#805ad5'});});
    var cy=(total>0||d.comments>0)?24:0,cx=0;
    chips.slice(0,3).forEach(function(ch){var lb=ch.t.length>22?ch.t.slice(0,21)+'…':ch.t;var w=lb.length*5.6+8;
      g.appendChild(svgEl('rect',{x:cx,y:cy,width:w,height:15,rx:7,fill:ch.c,opacity:0.92}));
      var t=svgEl('text',{x:cx+5,y:cy+11,'font-size':9,fill:'#fff'});t.textContent=lb;g.appendChild(t);cx+=w+4;});
    if(chips.length>3){var mo=svgEl('text',{x:cx,y:cy+11,'font-size':9,fill:'#718096'});mo.textContent='+'+(chips.length-3);g.appendChild(mo);}
    return g;
  }
  function drawLayer(){
    document.querySelectorAll('.annot-viz').forEach(function(e){e.remove();});
    if(typeof graph==='undefined')return;
    var agg=store.aggregates||{};
    Object.keys(agg).forEach(function(k){
      var i=k.indexOf(':');var tk=k.slice(0,i),tid=k.slice(i+1);
      var cell=graph.getCellById(tid);if(!cell)return;
      var view=graph.findViewByCell(cell);if(!view||!view.container)return;
      var g=makeMarker(agg[k],labelsFor(tk,tid,'fallacy'),labelsFor(tk,tid,'bias'));
      if(tk==='node'){var sz=cell.getSize?cell.getSize():{width:220,height:55};g.setAttribute('transform','translate(0,'+(sz.height+7)+')');}
      else{var bb=cell.getBBox();g.setAttribute('transform','translate('+(bb.x+bb.width/2-24)+','+(bb.y+bb.height/2-8)+')');}
      view.container.appendChild(g);
    });
  }
  function myPlaus(){if(!sel)return null;var f=store.annotations.filter(function(a){return a.mine&&a.kind==='plausibility'&&a.target_kind===sel.kind&&a.target_id===sel.id;});return f.length?f[0]:null;}
  function threadHtml(){
    var here=store.annotations.filter(function(a){return a.target_kind===sel.kind&&a.target_id===sel.id;});
    var mp=myPlaus();var h='';
    h+='<div class="annot-target"><span class="annot-tk">'+esc(sel.kind==='edge'?T.annot_target_edge:T.annot_target_node)+'</span><div>'+esc(sel.label)+'</div></div>';
    if(store.open){
      h+='<div class="annot-lbl">'+esc(T.annot_plaus)+'</div><div class="annot-plaus">';
      for(var v=1;v<=5;v++){h+='<button class="annot-p'+((mp&&mp.payload&&mp.payload.value===v)?' on':'')+'" onclick="__annotPlaus('+v+')">'+v+'</button>';}
      h+='</div>';
      h+='<textarea id="annot-comment" rows="2" placeholder="'+escA(T.annot_comment_ph)+'"></textarea>';
      h+='<button class="annot-add" onclick="__annotAdd(\'comment\')">'+esc(T.annot_add)+'</button>';
      h+='<div class="annot-flags"><input id="annot-fal" type="text" list="annot-fallacies-list" placeholder="'+escA(T.annot_fallacy)+'"><button class="annot-mini" onclick="__annotAdd(\'fallacy\')">'+esc(T.annot_add)+'</button></div>';
      h+='<div class="annot-flags"><input id="annot-bias" type="text" list="annot-biases-list" placeholder="'+escA(T.annot_bias)+'"><button class="annot-mini" onclick="__annotAdd(\'bias\')">'+esc(T.annot_add)+'</button></div>';
    }else{h+='<div class="annot-note">'+esc(T.annot_closed_note)+'</div>';}
    var list=here.filter(function(a){return a.kind!=='plausibility';});
    if(!list.length){h+='<div class="annot-empty">'+esc(T.annot_none)+'</div>';}
    else{h+='<div class="annot-list">'+list.map(function(a){
      var mark=(a.kind==='fallacy'||a.kind==='bias')?'⚠ ':'';
      var txt=a.kind==='comment'?((a.payload&&a.payload.text)||''):((a.payload&&a.payload.label)||'');
      return '<div class="annot-item"><div class="annot-au">'+esc(a.author_name||'')+'</div><div class="annot-tx">'+esc(mark+txt)+'</div>'+((a.mine||ANNOT.canAdmin)?'<button class="annot-del" onclick="__annotDel('+a.id+')">'+esc(T.annot_delete)+'</button>':'')+'</div>';
    }).join('')+'</div>';}
    return h;
  }
  function catalogHtml(){var h='';[['fallacies',T.annot_fallacy],['biases',T.annot_bias]].forEach(function(p){h+='<div class="annot-lbl">'+esc(p[1])+'</div>';var root=(typeof SCHEMES_DATA!=='undefined'?SCHEMES_DATA:{})[p[0]]||{};Object.keys(root).forEach(function(fk){((root[fk]||{})[p[0]]||[]).forEach(function(it){if(it&&it.name){var d=it.definition||it.description||it.desc||it.gloss||'';h+='<div class="annot-cat-item"><b>'+esc(it.name)+'</b>'+(d?'<br><span style="color:#718096">'+esc(d)+'</span>':'')+'</div>';}});});});return h;}
  window.__annotCatalog=function(){var v=document.getElementById('annot-cat-view');if(!v)return;v.innerHTML=v.innerHTML?'':catalogHtml();};
  function studentHome(){return '<div class="annot-empty">'+esc(T.annot_select_hint)+'</div><button class="annot-mini" style="width:100%;margin-top:10px" onclick="__annotCatalog()">📖 '+esc(T.annot_fallacy)+' / '+esc(T.annot_bias)+'</button><div id="annot-cat-view"></div>';}
  function ownerThreadEl(){var e=document.getElementById('annot-thread');if(!e){var ep=document.getElementById('edit-panel');if(!ep)return null;e=document.createElement('div');e.id='annot-thread';ep.appendChild(e);}return e;}
  function renderShare(){var ep=document.getElementById('edit-panel');if(!ep)return;var sh=document.getElementById('annot-share');if(!layerOn){if(sh)sh.remove();return;}if(!sh){sh=document.createElement('div');sh.id='annot-share';ep.insertBefore(sh,ep.firstChild);}var h='<div class="annot-lbl">'+esc(T.annot_sharing)+'</div><div class="annot-status">'+esc(store.open?T.annot_status_open:T.annot_status_closed)+'</div><button class="annot-add" onclick="__annotOpenClose()">'+esc(store.open?T.annot_close:T.annot_open)+'</button>';if(ANNOT.token){var link=location.origin+'/annotate/'+ANNOT.token;h+='<input class="annot-link" readonly value="'+escA(link)+'"><button class="annot-mini" onclick="__annotCopy(this,\''+link+'\')">'+esc(T.annot_copy)+'</button>';}h+='<button class="annot-mini annot-danger" onclick="__annotNewSession()">'+esc(T.annot_new_session)+'</button>';h+='<button class="annot-mini" style="width:100%;margin-top:6px" onclick="__annotDetached()">'+esc(T.annot_detached)+'</button>';h+='<label style="display:flex;align-items:center;gap:6px;margin-top:8px;font-size:11px;color:#4a5568;cursor:pointer"><input type="checkbox" '+(ANNOT.anon?'checked':'')+' onclick="__annotAnon(this.checked)" style="width:auto;margin:0"> '+esc(T.annot_anon)+'</label>';sh.innerHTML=h;}
  function renderThread(){
    if(ownerMode){var el=ownerThreadEl();if(!el)return;if(!sel){el.style.display='none';el.innerHTML='';}else{el.style.display='';el.innerHTML=threadHtml();}}
    else{if(!body)return;body.innerHTML=sel?('<button class="annot-linkbtn" onclick="__annotBack()">'+esc(T.annot_back)+'</button>'+threadHtml()):studentHome();}
  }
  async function post(kind,payload){if(!sel)return;await api('/api/maps/'+ANNOT.mapId+'/annotations',{method:'POST',body:JSON.stringify({target_kind:sel.kind,target_id:sel.id,kind:kind,payload:payload})});poll();}
  window.__annotPlaus=function(v){post('plausibility',{value:v});};
  window.__annotAdd=function(kind){
    if(kind==='comment'){var ta=document.getElementById('annot-comment');var tx=((ta&&ta.value)||'').trim();if(!tx)return;post('comment',{text:tx});}
    else{var li=document.getElementById(kind==='fallacy'?'annot-fal':'annot-bias');var lb=((li&&li.value)||'').trim();if(!lb)return;post(kind,{label:lb});if(li)li.value='';}
  };
  window.__annotDel=async function(id){await api('/api/annotations/'+id,{method:'DELETE'});poll();};
  window.__annotOpenClose=async function(){var path=store.open?'close':'open';var r=await api('/api/maps/'+ANNOT.mapId+'/annotate/'+path,{method:'POST'});if(r.ok){var j=await r.json();if(j.token)ANNOT.token=j.token;store.open=!store.open;if(ownerMode)renderShare();drawLayer();renderThread();}};
  window.__annotNewSession=async function(){if(!confirm(T.annot_new_session_confirm))return;await api('/api/maps/'+ANNOT.mapId+'/annotate/new-session',{method:'POST'});poll();};
  window.__annotCopy=function(btn,link){navigator.clipboard.writeText(link).then(function(){var o=btn.textContent;btn.textContent=T.annot_copied;setTimeout(function(){btn.textContent=o;},1200);});};
  window.__annotDetached=async function(){
    var r=await api('/api/maps/'+ANNOT.mapId+'/annotations/detached');if(!r.ok)return;var j=await r.json();var items=j.annotations||[];
    var ov=document.getElementById('annot-det-overlay');
    if(!ov){ov=document.createElement('div');ov.id='annot-det-overlay';ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9500;display:flex;align-items:center;justify-content:center';ov.onclick=function(e){if(e.target===ov)ov.style.display='none';};document.body.appendChild(ov);}
    var h='<div style="background:#fff;border-radius:10px;max-width:520px;width:92%;max-height:80vh;overflow:auto;padding:18px 20px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><h3 style="margin:0;font-size:14px;color:#1a202c">'+esc(T.annot_detached_title)+' ('+items.length+')</h3><button onclick="document.getElementById(\'annot-det-overlay\').style.display=\'none\'" style="background:none;border:none;font-size:16px;cursor:pointer;color:#718096">✕</button></div>';
    if(!items.length){h+='<div style="color:#a0aec0;font-size:12px">'+esc(T.annot_detached_none)+'</div>';}
    else{h+='<button class="annot-mini annot-danger" style="width:100%;margin-bottom:10px" onclick="__annotDetachedClear()">'+esc(T.annot_detached_clear)+'</button>';
      h+=items.map(function(a){var mark=(a.kind==='fallacy'||a.kind==='bias')?'⚠ ':'';var txt=a.kind==='comment'?((a.payload&&a.payload.text)||''):(a.kind==='plausibility'?('★ '+((a.payload&&a.payload.value)||'')):((a.payload&&a.payload.label)||''));return '<div class="annot-item"><div class="annot-au">'+esc(a.author_name||'')+' · '+esc(a.kind)+'</div><div class="annot-tx">'+esc(mark+txt)+'</div></div>';}).join('');}
    h+='</div>';ov.innerHTML=h;ov.style.display='flex';
  };
  window.__annotDetachedClear=async function(){await api('/api/maps/'+ANNOT.mapId+'/annotations/detached',{method:'DELETE'});var ov=document.getElementById('annot-det-overlay');if(ov)ov.style.display='none';poll();};
  window.__annotAnon=async function(v){await api('/api/maps/'+ANNOT.mapId+'/annotate/anon',{method:'POST',body:JSON.stringify({anon:v})});ANNOT.anon=v;};
  if(btn){btn.style.display='';btn.textContent=T.annot_enter;btn.onclick=window.__annotToggle;}
  if(studentMode&&ANNOT.auto){['btn-select','btn-connect','btn-guided','btn-annotate'].forEach(function(id){var b=document.getElementById(id);if(b)b.style.display='none';});}
  if(ANNOT.auto){enter();}
})();
"""


def _annotation_snippet(ctx: dict, t: dict) -> str:
    keys = ('annot_title', 'annot_enter', 'annot_exit', 'annot_sharing', 'annot_open', 'annot_close',
            'annot_status_open', 'annot_status_closed', 'annot_open_hint', 'annot_copy', 'annot_copied',
            'annot_new_session', 'annot_new_session_confirm', 'annot_select_hint', 'annot_target_node',
            'annot_target_edge', 'annot_plaus', 'annot_comment_ph', 'annot_add', 'annot_fallacy',
            'annot_bias', 'annot_label_ph', 'annot_none', 'annot_delete', 'annot_closed_note', 'annot_back',
            'annot_detached', 'annot_detached_title', 'annot_detached_none', 'annot_detached_clear',
            'annot_anon')
    cfg = {
        "mapId": ctx["map_id"], "canAdmin": bool(ctx.get("can_admin")),
        "canWrite": bool(ctx.get("can_write")), "auto": bool(ctx.get("auto")),
        "token": ctx.get("token"), "anon": bool(ctx.get("anon")), "owner": bool(ctx.get("owner")),
        "t": {k: t.get(k, k) for k in keys},
    }
    panel = ('<div id="annot-panel"><div id="annot-head"><span id="annot-title"></span>'
             '<button id="annot-x" onclick="__annotClosePanel()">✕</button></div>'
             '<div id="annot-body"></div></div>')
    return ("<style>" + _ANNOT_CSS + "</style>" + panel +
            "<script>\nwindow.ANNOT = " + json.dumps(cfg, ensure_ascii=False) + ";\n" +
            _ANNOT_JS + "\n</script>")


def _inject_web_ui(html: str, map_id: int | None, can_debate: bool, has_reasoning: bool = False, is_owner: bool = True, owner_name: str = "", lang: str = 'en', annotate: dict | None = None) -> str:
    # Architectural note: this function appends a <script> block to the self-contained
    # HTML produced by generate_html_x6(). It injects backend-aware UI (save, share,
    # debate) that needs to know map_id, permissions, and ownership at serve time.
    # The JS uses Python f-string {{ }} escaping for literal braces.
    # Tradeoff: keeps the visualizer decoupled from the backend, but this function
    # is large and mixes Python control flow with inline JS — refactor if it grows further.
    t    = _locales.get_t(lang)
    ui_t = {k: t[k] for k in (
        'loading', 'close', 'error',
        'viewer_back', 'viewer_reviewing', 'viewer_save', 'viewer_saving', 'viewer_saved',
        'viewer_share', 'viewer_export', 'viewer_export_share', 'viewer_share_link',
        'viewer_copy', 'viewer_copied', 'viewer_revoke', 'viewer_no_link',
        'viewer_revoke_confirm', 'viewer_course', 'viewer_reasoning', 'viewer_analysis_title',
        'viewer_debate_btn', 'app_no_course',
        'debate_intro_text', 'debate_opponent', 'debate_defender',
        'debate_desc_con', 'debate_desc_pro', 'debate_start', 'debate_save_first',
        'debate_reply_ph', 'debate_send', 'debate_reset', 'debate_failed',
    )}
    snippet = f"""
<div id="analysis-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;align-items:center;justify-content:center">
  <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:12px;padding:1.5rem;width:100%;max-width:660px;max-height:80vh;display:flex;flex-direction:column">
    <div style="font-size:1rem;font-weight:600;color:#e2e8f0;margin-bottom:1rem;flex-shrink:0" id="analysis-modal-title">{t['viewer_analysis_title']}</div>
    <div id="analysis-modal-body" style="overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:1rem"></div>
    <div style="margin-top:1.2rem;flex-shrink:0;text-align:right">
      <button onclick="document.getElementById('analysis-modal').style.display='none'"
              style="padding:.4rem 1rem;background:#2d3148;color:#e2e8f0;border:none;border-radius:6px;cursor:pointer;font-size:.85rem">{t['close']}</button>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
.debate-md p {{ margin: 0 0 .4em; }}
.debate-md p:last-child {{ margin-bottom: 0; }}
.debate-md strong {{ color: #e2e8f0; }}
.debate-md em {{ color: #cbd5e0; }}
.debate-md ul, .debate-md ol {{ padding-left: 1.2em; margin: .3em 0; }}
.debate-md li {{ margin-bottom: .15em; }}
.debate-md code {{ background: rgba(0,0,0,.35); border-radius: 3px; padding: .1em .3em; font-size: .75rem; }}
</style>
<div id="debate-panel" style="display:none;position:fixed;right:0;top:0;height:100vh;width:380px;background:#1a1d27;border-left:1px solid #2d3148;z-index:8000;flex-direction:column;font-family:system-ui,sans-serif;box-shadow:-4px 0 20px rgba(0,0,0,.4)">
  <div style="padding:.75rem 1rem;border-bottom:1px solid #2d3148;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;background:#141722">
    <span style="font-size:.88rem;font-weight:600;color:#e2e8f0">💬 Debate-A-Bot</span>
    <button id="debate-close-btn" style="background:none;border:none;color:#718096;font-size:1rem;cursor:pointer;line-height:1;padding:2px 6px">✕</button>
  </div>
  <div id="debate-intro" style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1rem;padding:1.5rem 1.2rem">
    <p style="color:#a0aec0;font-size:.8rem;text-align:center;margin:0;max-width:280px">{t['debate_intro_text']}</p>
    <div style="display:flex;gap:.5rem">
      <button id="mode-btn-con" class="debate-mode-btn" data-mode="con" style="padding:.45rem .9rem;border-radius:6px;border:1px solid #4a5568;background:#2d3748;color:#e2e8f0;font-size:.8rem;cursor:pointer">{t['debate_opponent']}</button>
      <button id="mode-btn-pro" class="debate-mode-btn" data-mode="pro" style="padding:.45rem .9rem;border-radius:6px;border:1px solid #2d3148;background:#0f1117;color:#718096;font-size:.8rem;cursor:pointer">{t['debate_defender']}</button>
    </div>
    <p id="debate-mode-desc" style="color:#718096;font-size:.75rem;text-align:center;max-width:280px;margin:0">{t['debate_desc_con']}</p>
    <button id="debate-start-btn" style="padding:.5rem 1.4rem;background:#0a3c8a;color:#fff;border:none;border-radius:6px;font-size:.85rem;cursor:pointer;margin-top:.3rem">{t['debate_start']}</button>
  </div>
  <div id="debate-chat" style="display:none;flex:1;flex-direction:column;min-height:0">
    <div id="debate-messages" style="flex:1;overflow-y:auto;padding:.75rem .8rem;display:flex;flex-direction:column;gap:.6rem"></div>
    <div style="padding:.5rem .7rem;border-top:1px solid #2d3148;display:flex;gap:.4rem;flex-shrink:0;background:#141722">
      <textarea id="debate-input" rows="2" placeholder="{t['debate_reply_ph']}" style="flex:1;background:#0f1117;border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;font-size:.8rem;padding:.4rem .55rem;resize:none;outline:none;font-family:inherit;line-height:1.45"></textarea>
      <div style="display:flex;flex-direction:column;gap:.3rem">
        <button id="debate-send-btn" style="padding:.35rem .7rem;background:#0a3c8a;color:#fff;border:none;border-radius:5px;font-size:.78rem;cursor:pointer;white-space:nowrap">{t['debate_send']}</button>
        <button id="debate-reset-btn" style="padding:.35rem .7rem;background:#2d3148;color:#a0aec0;border:none;border-radius:5px;font-size:.78rem;cursor:pointer">{t['debate_reset']}</button>
      </div>
    </div>
  </div>
</div>
<script>
(function() {{
  const UI_T         = {json.dumps(ui_t, ensure_ascii=False)};
  let MAP_ID          = {json.dumps(map_id)};
  const CAN_DEBATE    = {json.dumps(can_debate)};
  const HAS_REASONING = {json.dumps(has_reasoning)};
  const IS_OWNER      = {json.dumps(is_owner)};
  const OWNER_NAME    = {json.dumps(owner_name)};

  // ── Inject buttons into existing toolbar ──────────────────────────────────
  const toolbar = document.getElementById('toolbar');

  // Back button — prepended at the start of toolbar
  const backBtn = document.createElement('button');
  backBtn.textContent = UI_T.viewer_back;
  backBtn.className = 'tb-btn';
  backBtn.onclick = () => window.location.href = '/app';
  toolbar.insertBefore(backBtn, toolbar.firstChild);

  // Save button (owners only) — or read-only badge for reviewers
  let _userCourses = [];

  if (!IS_OWNER) {{
    const badge = document.createElement('span');
    badge.textContent = UI_T.viewer_reviewing.replace('{{name}}', OWNER_NAME);
    badge.style.cssText = 'font-size:.78rem;color:#718096;padding:0 6px;white-space:nowrap;align-self:center';
    toolbar.appendChild(badge);
  }}

  const saveBtn = document.createElement('button');
  saveBtn.textContent = UI_T.viewer_save;
  saveBtn.className = 'tb-btn';
  saveBtn.style.background = '#0a3c8a';
  saveBtn.style.color = '#fff';
  if (!IS_OWNER) {{ saveBtn.style.display = 'none'; }}
  saveBtn.onclick = async function() {{
    const state = _captureState();
    if (!state) return;
    const title = state.title || 'Argument Map';
    saveBtn.textContent = UI_T.viewer_saving;
    saveBtn.disabled = true;
    try {{
      if (MAP_ID) {{
        const res = await fetch('/api/maps/' + MAP_ID, {{
          method: 'PUT',
          headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{ title, map_data: state }})
        }});
        if (!res.ok) {{
          const err = await res.json().catch(() => ({{}}));
          saveBtn.textContent = UI_T.error;
          saveBtn.disabled = false;
          console.error('Save failed', res.status, err);
          return;
        }}
      }} else {{
        let courseId = null;
        if (_userCourses.length === 1) {{
          courseId = _userCourses[0].id;
        }} else if (_userCourses.length > 1) {{
          const sel = document.getElementById('_course-sel');
          if (sel) courseId = parseInt(sel.value) || null;
        }}
        const res = await fetch('/api/maps', {{
          method: 'POST',
          headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{ title, map_data: state, course_id: courseId }})
        }});
        const {{ id }} = await res.json();
        MAP_ID = id;
        history.replaceState(null, '', '/map/' + id);
      }}
      saveBtn.textContent = UI_T.viewer_saved;
      setTimeout(() => {{ saveBtn.textContent = UI_T.viewer_save; saveBtn.disabled = false; }}, 1500);
    }} catch(e) {{
      saveBtn.textContent = UI_T.error;
      saveBtn.disabled = false;
    }}
  }};
  toolbar.appendChild(saveBtn);

  // Share & Export modal — always visible (export for all, share link for owners of saved maps)
  if (IS_OWNER) {{
    const shareBtn = document.createElement('button');
    shareBtn.textContent = UI_T.viewer_share;
    shareBtn.className = 'tb-btn';
    shareBtn.style.cssText = 'background:#1a3348;color:#63b3ed;border-color:#2a4a6a';

    // Modal overlay
    const overlay = document.createElement('div');
    overlay.id = '_share-overlay';
    overlay.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9000;align-items:center;justify-content:center';
    overlay.innerHTML = `
      <div style="background:#1a1d27;border:1px solid #2d3148;border-radius:10px;padding:1.5rem 1.6rem;width:100%;max-width:400px;box-shadow:0 12px 40px rgba(0,0,0,.6)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.2rem">
          <span style="font-size:.88rem;font-weight:700;color:#e2e8f0">{t['viewer_export_share']}</span>
          <button id="_share-close" style="background:none;border:none;color:#718096;font-size:1rem;cursor:pointer;line-height:1;padding:2px 6px">&#x2715;</button>
        </div>

        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:#4a5568;margin-bottom:.6rem">{t['viewer_export']}</div>
        <div style="display:flex;gap:.5rem;margin-bottom:1.2rem">
          <button id="_exp-json" style="flex:1;padding:.45rem;background:#0f1117;border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;font-size:.78rem;cursor:pointer">JSON</button>
          <button id="_exp-svg"  style="flex:1;padding:.45rem;background:#0f1117;border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;font-size:.78rem;cursor:pointer">SVG</button>
          <button id="_exp-png"  style="flex:1;padding:.45rem;background:#0f1117;border:1px solid #2d3148;border-radius:6px;color:#e2e8f0;font-size:.78rem;cursor:pointer">PNG</button>
        </div>

        <div id="_share-section" style="display:none">
          <div style="border-top:1px solid #2d3148;padding-top:1rem;margin-bottom:.6rem">
            <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:#4a5568;margin-bottom:.6rem">{t['viewer_share_link']}</div>
            <div style="display:flex;gap:.5rem;align-items:center;margin-bottom:.6rem">
              <input id="_share-url" readonly style="flex:1;padding:.35rem .6rem;background:#0f1117;border:1px solid #2d3148;border-radius:5px;color:#a0aec0;font-size:.72rem;outline:none;font-family:monospace">
              <button id="_share-copy" style="padding:.35rem .7rem;background:#0a3c8a;color:#fff;border:none;border-radius:5px;font-size:.75rem;cursor:pointer;white-space:nowrap">{t['viewer_copy']}</button>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <button id="_share-revoke" style="background:none;border:none;color:#fc8181;font-size:.72rem;cursor:pointer;padding:0">{t['viewer_revoke']}</button>
              <span id="_share-loading" style="font-size:.72rem;color:#718096"></span>
            </div>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.addEventListener('click', function(e) {{
      if (e.target === overlay) overlay.style.display = 'none';
    }});
    document.getElementById('_share-close').onclick = () => overlay.style.display = 'none';
    document.getElementById('_exp-json').onclick = () => {{ exportJSON(); }};
    document.getElementById('_exp-svg').onclick  = () => {{ exportSVG(); }};
    document.getElementById('_exp-png').onclick  = () => {{ exportPNG(); }};

    if (MAP_ID) {{
      document.getElementById('_share-section').style.display = 'block';

      document.getElementById('_share-copy').onclick = function() {{
        const url = document.getElementById('_share-url');
        url.select(); url.setSelectionRange(0, 9999);
        navigator.clipboard.writeText(url.value).then(() => {{
          this.textContent = UI_T.viewer_copied;
          setTimeout(() => this.textContent = UI_T.viewer_copy, 1500);
        }});
      }};

      document.getElementById('_share-revoke').onclick = async function() {{
        if (!confirm(UI_T.viewer_revoke_confirm)) return;
        await fetch('/api/maps/' + MAP_ID + '/share', {{ method: 'DELETE' }});
        document.getElementById('_share-url').value = '';
        document.getElementById('_share-url').placeholder = UI_T.viewer_no_link;
        document.getElementById('_share-copy').disabled = true;
        this.style.display = 'none';
      }};
    }}

    shareBtn.onclick = async function() {{
      if (overlay.style.display !== 'none') {{ overlay.style.display = 'none'; return; }}
      overlay.style.display = 'flex';
      if (MAP_ID) {{
        document.getElementById('_share-loading').textContent = UI_T.loading;
        const res  = await fetch('/api/maps/' + MAP_ID + '/share', {{ method: 'POST' }});
        const data = await res.json();
        document.getElementById('_share-url').value = window.location.origin + '/share/' + data.token;
        document.getElementById('_share-url').placeholder = '';
        document.getElementById('_share-copy').disabled = false;
        document.getElementById('_share-revoke').style.display = '';
        document.getElementById('_share-loading').textContent = '';
      }}
    }};

    toolbar.appendChild(shareBtn);
  }}

  // For new maps: fetch courses and inject a select in the toolbar if there are multiple
  if (!MAP_ID) {{
    fetch('/api/courses').then(r => r.json()).then(courses => {{
      _userCourses = courses;
      if (courses.length > 1) {{
        const label = document.createElement('label');
        label.textContent = UI_T.viewer_course;
        label.style.cssText = 'font-size:.75rem;color:#a0aec0;white-space:nowrap;align-self:center;margin-right:2px';
        const sel = document.createElement('select');
        sel.id = '_course-sel';
        sel.style.cssText = 'padding:.25rem .45rem;background:#0f1117;border:1px solid #2d3148;border-radius:4px;color:#e2e8f0;font-size:.78rem;outline:none';
        const none = document.createElement('option');
        none.value = '';
        none.textContent = UI_T.app_no_course;
        sel.appendChild(none);
        courses.forEach(c => {{
          const o = document.createElement('option');
          o.value = c.id;
          o.textContent = c.name;
          sel.appendChild(o);
        }});
        toolbar.insertBefore(label, saveBtn);
        toolbar.insertBefore(sel, saveBtn);
      }}
    }});
  }}

  // Analysis button (if reasoning was saved)
  if (HAS_REASONING && MAP_ID) {{
    const analysisBtn = document.createElement('button');
    analysisBtn.textContent = UI_T.viewer_reasoning;
    analysisBtn.className = 'tb-btn';
    analysisBtn.style.cssText = 'background:#1a3a2a;color:#48bb78;border-color:#2d5a3d';
    analysisBtn.onclick = async function() {{
      const modal = document.getElementById('analysis-modal');
      const body  = document.getElementById('analysis-modal-body');
      const title = document.getElementById('analysis-modal-title');
      title.textContent = (document.getElementById('map-title')?.textContent || '') + ' — ' + UI_T.viewer_reasoning;
      body.innerHTML = '<p style="color:#718096;font-size:.82rem">' + UI_T.loading + '</p>';
      modal.style.display = 'flex';
      const steps = await fetch('/api/maps/' + MAP_ID + '/reasoning').then(r => r.json());
      body.innerHTML = steps.filter(s => !s.step.includes('Step 4')).map(s => `
        <div>
          <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#48bb78;margin-bottom:.35rem">${{s.step}}</div>
          <pre style="font-size:.75rem;color:#a0aec0;font-family:monospace;white-space:pre-wrap;line-height:1.55;background:#0f1117;border:1px solid #2d3148;border-radius:5px;padding:.6rem .8rem;margin:0">${{(s.reasoning||'').replace(/</g,'&lt;')}}</pre>
        </div>
      `).join('');
    }};
    toolbar.appendChild(analysisBtn);
  }}

  // Debate button (if permitted)
  if (CAN_DEBATE) {{
    const debateBtn = document.createElement('button');
    debateBtn.textContent = UI_T.viewer_debate_btn;
    debateBtn.className = 'tb-btn';
    debateBtn.onclick = () => openDebatePanel();
    toolbar.appendChild(debateBtn);
  }}

  // ── Debate panel logic ────────────────────────────────────────────────────
  let _debateMode = 'con';
  let _debateHistory = [];
  let _debateBusy = false;

  function openDebatePanel() {{
    document.getElementById('debate-panel').style.display = 'flex';
  }}

  document.getElementById('debate-close-btn').onclick = function() {{
    document.getElementById('debate-panel').style.display = 'none';
  }};

  document.querySelectorAll('.debate-mode-btn').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      _debateMode = btn.dataset.mode;
      document.querySelectorAll('.debate-mode-btn').forEach(function(b) {{
        const active = b.dataset.mode === _debateMode;
        b.style.background   = active ? '#2d3748' : '#0f1117';
        b.style.color        = active ? '#e2e8f0' : '#718096';
        b.style.borderColor  = active ? '#4a5568' : '#2d3148';
      }});
      document.getElementById('debate-mode-desc').textContent = _debateMode === 'con'
        ? UI_T.debate_desc_con
        : UI_T.debate_desc_pro;
    }});
  }});

  document.getElementById('debate-start-btn').onclick = function() {{
    if (!MAP_ID) {{
      document.getElementById('debate-mode-desc').textContent = UI_T.debate_save_first;
      document.getElementById('debate-mode-desc').style.color = '#fc8181';
      return;
    }}
    document.getElementById('debate-intro').style.display = 'none';
    document.getElementById('debate-chat').style.display = 'flex';
    _debateHistory = [{{role: 'user', content: 'Please begin your analysis.'}}];
    _streamDebate();
  }};

  document.getElementById('debate-send-btn').onclick = function() {{
    if (_debateBusy) return;
    const input = document.getElementById('debate-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    _debateHistory.push({{role: 'user', content: text}});
    _appendDebateMsg('user', text);
    _streamDebate();
  }};

  document.getElementById('debate-input').addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      document.getElementById('debate-send-btn').click();
    }}
  }});

  document.getElementById('debate-reset-btn').onclick = function() {{
    _debateHistory = [];
    document.getElementById('debate-messages').innerHTML = '';
    document.getElementById('debate-chat').style.display = 'none';
    document.getElementById('debate-intro').style.display = 'flex';
  }};

  function _appendDebateMsg(role, content) {{
    const msgs = document.getElementById('debate-messages');
    const div = document.createElement('div');
    div.style.cssText = role === 'user'
      ? 'align-self:flex-end;max-width:85%;background:#0a3c8a;color:#e2e8f0;padding:.45rem .7rem;border-radius:10px 10px 3px 10px;font-size:.8rem;line-height:1.5;white-space:pre-wrap'
      : 'align-self:flex-start;max-width:92%;background:#1e2336;color:#cbd5e0;padding:.45rem .7rem;border-radius:10px 10px 10px 3px;font-size:.8rem;line-height:1.5';
    if (role === 'user') {{
      div.textContent = content;
    }} else {{
      div.className = 'debate-md';
      div.innerHTML = (typeof marked !== 'undefined' && content) ? marked.parse(content) : content;
    }}
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }}

  async function _streamDebate() {{
    if (_debateBusy) return;
    _debateBusy = true;
    const sendBtn = document.getElementById('debate-send-btn');
    const input   = document.getElementById('debate-input');
    sendBtn.disabled = true;
    input.disabled = true;

    const bubble = _appendDebateMsg('assistant', '…');
    let accumulated = '';

    try {{
      const res = await fetch('/api/maps/' + MAP_ID + '/debate', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{messages: _debateHistory, mode: _debateMode}})
      }});
      if (!res.ok) {{ bubble.textContent = UI_T.debate_failed + ' (' + res.status + ').'; return; }}
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      outer: while (true) {{
        const {{done, value}} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {{stream: true}});
        const lines = buf.split('\\n');
        buf = lines.pop();
        for (const line of lines) {{
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') break outer;
          try {{
            const obj = JSON.parse(payload);
            if (obj.delta) {{
              if (!accumulated) bubble.textContent = '';
              accumulated += obj.delta;
              bubble.textContent = accumulated;
              document.getElementById('debate-messages').scrollTop = 99999;
            }}

            if (obj.error) {{ bubble.textContent = UI_T.error + ': ' + obj.error; break outer; }}
            if (obj.done) break outer;
          }} catch (_) {{}}
        }}
      }}
      if (accumulated) {{
        _debateHistory.push({{role: 'assistant', content: accumulated}});
        bubble.className = 'debate-md';
        if (typeof marked !== 'undefined') bubble.innerHTML = marked.parse(accumulated);
      }}
    }} catch(e) {{
      bubble.textContent = UI_T.debate_failed;
    }} finally {{
      _debateBusy = false;
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }}
  }}
}})();
</script>
</body>"""
    if annotate:
        snippet = snippet + _annotation_snippet(annotate, t)
    return html.replace('</body>', snippet)


# Prevent Caddy and browsers from caching map HTML pages.
# Without this, a teacher viewing a student's map may see a stale version
# even after the student saves, because Caddy serves the cached response.
_NO_CACHE = {"Cache-Control": "no-store"}

@app.get("/map", response_class=HTMLResponse)
def new_map(request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    lang = _get_lang(request)
    guided = request.query_params.get("mode") == "guided"
    html = generate_html_x6({}, "output.html", return_html=True, lang=lang, guided=guided)
    return HTMLResponse(_inject_web_ui(html, None, user.has_permission("debate"), lang=lang), headers=_NO_CACHE)


@app.get("/map/{map_id}", response_class=HTMLResponse)
def open_map(map_id: int, request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if m.user_id != user.id:
        if not user.has_permission("view_course_maps"):
            raise HTTPException(403, "Forbidden")
        course = db.query(Course).filter(Course.id == m.course_id).first()
        if not course or not any(t.id == user.id for t in course.teachers):
            raise HTTPException(403, "Forbidden")
    lang = _get_lang(request)
    is_owner = m.user_id == user.id
    # Guided mode can be requested on an existing map (e.g. a template instance).
    guided = is_owner and request.query_params.get("mode") == "guided"
    slots = None
    if guided and m.template_id:
        tmpl = db.query(Template).filter(Template.id == m.template_id).first()
        slots = tmpl.slots if tmpl else None
    html = generate_html_x6(m.map_data, "output.html", return_html=True, lang=lang, guided=guided, slots=slots)
    # The owner — or a teacher of the map's course — can open/manage the annotation layer.
    can_admin = is_owner
    if not can_admin and user.has_permission("view_course_maps") and m.course_id:
        c = db.query(Course).filter(Course.id == m.course_id).first()
        can_admin = bool(c and any(tt.id == user.id for tt in c.teachers))
    annotate = {"map_id": m.id, "can_admin": can_admin, "can_write": bool(m.annotate_open),
                "auto": False, "token": m.annotate_token, "anon": bool(m.annotate_anon),
                "owner": is_owner} if can_admin else None
    return HTMLResponse(_inject_web_ui(html, map_id, user.has_permission("debate"), m.reasoning is not None, is_owner=is_owner, owner_name=m.user.name or m.user.email, lang=lang, annotate=annotate), headers=_NO_CACHE)


# ── Public share ──────────────────────────────────────────────────────────────

@app.get("/share/{token}", response_class=HTMLResponse)
def shared_map(token: str, request: Request, db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.share_token == token).first()
    if not m:
        raise HTTPException(404, "Shared map not found")
    lang = _get_lang(request)
    html = generate_html_x6(m.map_data, "output.html", return_html=True, lang=lang)
    return HTMLResponse(
        _inject_web_ui(html, None, can_debate=False, is_owner=False,
                       owner_name=m.user.name or m.user.email, lang=lang),
        headers=_NO_CACHE,
    )


@app.post("/api/maps/{map_id}/share")
def create_share(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if not m.share_token:
        m.share_token = secrets.token_urlsafe(24)
        db.commit()
    return {"token": m.share_token}


@app.delete("/api/maps/{map_id}/share")
def revoke_share(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id, Map.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    m.share_token = None
    db.commit()
    return {"ok": True}


# ── Annotation layer (#3) ─────────────────────────────────────────────────────
# Annotations live in their own tables, entirely separate from map_data. Identity
# is the logged-in account when present, otherwise a permissive anonymous token
# cookie (RoomPulse-style). Realtime is client polling; no websockets.

def _map_annot_admin(map_id: int, user: User, db: Session) -> Map:
    """Owner, or a teacher of the map's course, may administer the annotation layer."""
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if m.user_id != user.id:
        if not user.has_permission("view_course_maps"):
            raise HTTPException(403, "Forbidden")
        course = db.query(Course).filter(Course.id == m.course_id).first()
        if not course or not any(t.id == user.id for t in course.teachers):
            raise HTTPException(403, "Forbidden")
    return m


def _active_session(map_id: int, db: Session, create: bool = False):
    s = (db.query(AnnotationSession)
         .filter(AnnotationSession.map_id == map_id, AnnotationSession.is_active == True)  # noqa: E712
         .order_by(AnnotationSession.id.desc()).first())
    if not s and create:
        s = AnnotationSession(map_id=map_id, is_active=True)
        db.add(s); db.commit(); db.refresh(s)
    return s


def _annot_identity(session: str | None, annot_token: str | None, db: Session):
    """Return (user_id_or_None, token_or_None, display_name)."""
    user = get_user_or_none(session, db)
    if user:
        return user.id, None, (user.name or user.email)
    return None, annot_token, "Anonymous"


@app.post("/api/maps/{map_id}/annotate/open")
def annotate_open(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    if not m.annotate_token:
        m.annotate_token = secrets.token_urlsafe(16)
    m.annotate_open = True
    _active_session(map_id, db, create=True)
    db.commit()
    return {"token": m.annotate_token, "open": True}


@app.post("/api/maps/{map_id}/annotate/close")
def annotate_close(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    m.annotate_open = False
    db.commit()
    return {"open": False}


@app.post("/api/maps/{map_id}/annotate/new-session")
def annotate_new_session(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    cur = _active_session(map_id, db)
    if cur:
        cur.is_active = False
    ns = AnnotationSession(map_id=map_id, is_active=True)
    db.add(ns); db.commit(); db.refresh(ns)
    return {"session_id": ns.id}


@app.post("/api/maps/{map_id}/annotate/anon")
def annotate_set_anon(map_id: int, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    m.annotate_anon = bool(body.get("anon"))
    db.commit()
    return {"anon": bool(m.annotate_anon)}


def _can_read_annotations(m: Map, user: User | None) -> bool:
    if m.annotate_open:
        return True
    return bool(user and (m.user_id == user.id or user.has_permission("view_course_maps")))


@app.get("/api/maps/{map_id}/annotations")
def list_annotations(map_id: int, session: str | None = Cookie(default=None),
                     annot_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    user = get_user_or_none(session, db)
    if not _can_read_annotations(m, user):
        raise HTTPException(403, "Forbidden")
    map_updated = m.updated_at.isoformat() if m.updated_at else None
    s = _active_session(map_id, db)
    if not s:
        return {"open": bool(m.annotate_open), "annotations": [], "aggregates": {}, "map_updated": map_updated}
    rows = (db.query(Annotation)
            .filter(Annotation.session_id == s.id, Annotation.status == "visible")
            .order_by(Annotation.created_at.asc()).all())
    my_uid, my_tok, _ = _annot_identity(session, annot_token, db)

    def is_mine(a):
        return ((a.author_user_id is not None and a.author_user_id == my_uid) or
                (a.author_token is not None and my_tok is not None and a.author_token == my_tok))

    out = [{"id": a.id, "target_kind": a.target_kind, "target_id": a.target_id,
            "kind": a.kind, "payload": a.payload, "author_name": a.author_name,
            "mine": is_mine(a)} for a in rows]
    agg: dict = {}
    for a in rows:
        d = agg.setdefault(a.target_kind + ":" + a.target_id,
                           {"plaus_sum": 0, "plaus_n": 0, "plaus_dist": [0, 0, 0, 0, 0],
                            "comments": 0, "fallacies": 0, "biases": 0})
        if a.kind == "plausibility" and a.payload and isinstance(a.payload.get("value"), (int, float)):
            v = int(a.payload["value"])
            d["plaus_sum"] += v; d["plaus_n"] += 1
            if 1 <= v <= 5:
                d["plaus_dist"][v - 1] += 1
        elif a.kind == "comment":  d["comments"]  += 1
        elif a.kind == "fallacy":  d["fallacies"] += 1
        elif a.kind == "bias":     d["biases"]    += 1
    for d in agg.values():
        d["plaus_mean"] = (d["plaus_sum"] / d["plaus_n"]) if d["plaus_n"] else None
    return {"open": bool(m.annotate_open), "annotations": out, "aggregates": agg, "map_updated": map_updated}


@app.get("/api/maps/{map_id}/annotate/data")
def annotate_map_data(map_id: int, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    """Map structure for annotators, so viewers can pick up the owner's live edits."""
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if not _can_read_annotations(m, get_user_or_none(session, db)):
        raise HTTPException(403, "Forbidden")
    return {"map_data": m.map_data, "updated_at": m.updated_at.isoformat() if m.updated_at else None}


class AnnotationCreate(BaseModel):
    target_kind: str
    target_id:   str
    kind:        str
    payload:     dict | None = None


@app.post("/api/maps/{map_id}/annotations")
def create_annotation(map_id: int, body: AnnotationCreate, response: Response,
                      session: str | None = Cookie(default=None),
                      annot_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if not m.annotate_open:
        raise HTTPException(403, "Annotation is closed")
    if body.target_kind not in ("node", "edge") or body.kind not in ("comment", "plausibility", "fallacy", "bias"):
        raise HTTPException(400, "Invalid annotation")
    my_uid, my_tok, my_name = _annot_identity(session, annot_token, db)
    if my_uid is None and not my_tok:
        my_tok = secrets.token_urlsafe(12)
        response.set_cookie("annot_token", my_tok, max_age=60 * 60 * 24 * 365, samesite="lax")
    s = _active_session(map_id, db, create=True)
    # Plausibility is one-per-author-per-target: upsert instead of stacking.
    if body.kind == "plausibility":
        q = db.query(Annotation).filter(
            Annotation.session_id == s.id, Annotation.kind == "plausibility",
            Annotation.target_kind == body.target_kind, Annotation.target_id == body.target_id)
        q = q.filter(Annotation.author_user_id == my_uid) if my_uid is not None \
            else q.filter(Annotation.author_token == my_tok)
        existing = q.first()
        if existing:
            existing.payload = body.payload
            db.commit()
            return {"id": existing.id}
    a = Annotation(session_id=s.id, map_id=map_id, target_kind=body.target_kind,
                   target_id=body.target_id, author_user_id=my_uid, author_token=my_tok,
                   author_name=my_name, kind=body.kind, payload=body.payload)
    db.add(a); db.commit(); db.refresh(a)
    return {"id": a.id}


def _own_annotation(ann_id: int, session, annot_token, db) -> Annotation:
    a = db.query(Annotation).filter(Annotation.id == ann_id).first()
    if not a:
        raise HTTPException(404, "Annotation not found")
    my_uid, my_tok, _ = _annot_identity(session, annot_token, db)
    mine = ((a.author_user_id is not None and a.author_user_id == my_uid) or
            (a.author_token is not None and my_tok is not None and a.author_token == my_tok))
    if not mine:
        user = get_user_or_none(session, db)
        m = db.query(Map).filter(Map.id == a.map_id).first()
        if not (user and m and (m.user_id == user.id or user.has_permission("view_course_maps"))):
            raise HTTPException(403, "Forbidden")
    return a


@app.patch("/api/annotations/{ann_id}")
def update_annotation(ann_id: int, body: dict, session: str | None = Cookie(default=None),
                      annot_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    a = _own_annotation(ann_id, session, annot_token, db)
    if "payload" in body:
        a.payload = body["payload"]
    db.commit()
    return {"id": a.id}


@app.delete("/api/annotations/{ann_id}")
def delete_annotation(ann_id: int, session: str | None = Cookie(default=None),
                      annot_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    a = _own_annotation(ann_id, session, annot_token, db)
    db.delete(a); db.commit()
    return {"ok": True}


def _detached_annotations(m: Map, db: Session):
    """Annotations in the active session whose target node/edge no longer exists in map_data."""
    data = m.map_data or {}
    valid = {str(n.get("id")) for n in data.get("nodes", []) if n.get("id")}
    valid |= {str(s.get("id")) for s in data.get("steps", []) if s.get("id")}
    s = _active_session(m.id, db)
    if not s:
        return []
    rows = db.query(Annotation).filter(Annotation.session_id == s.id, Annotation.status == "visible").all()
    return [a for a in rows if a.target_id not in valid]


@app.get("/api/maps/{map_id}/annotations/detached")
def list_detached(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    orphans = _detached_annotations(m, db)
    return {"count": len(orphans),
            "annotations": [{"id": a.id, "target_kind": a.target_kind, "target_id": a.target_id,
                             "kind": a.kind, "payload": a.payload, "author_name": a.author_name} for a in orphans]}


@app.delete("/api/maps/{map_id}/annotations/detached")
def clear_detached(map_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _map_annot_admin(map_id, user, db)
    orphans = _detached_annotations(m, db)
    for a in orphans:
        db.delete(a)
    db.commit()
    return {"cleared": len(orphans)}


@app.get("/annotate/{token}", response_class=HTMLResponse)
def annotate_page(token: str, request: Request,
                  session: str | None = Cookie(default=None),
                  annot_token: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    m = db.query(Map).filter(Map.annotate_token == token).first()
    if not m:
        raise HTTPException(404, "Annotation link not found")
    user = get_user_or_none(session, db)
    lang = _get_lang(request)
    html = generate_html_x6(m.map_data, "output.html", return_html=True, lang=lang)
    ctx = {"map_id": m.id, "can_admin": False, "can_write": bool(m.annotate_open),
           "auto": True, "token": m.annotate_token}
    # Anonymous sharing: hide the owner's name from annotators.
    owner_display = _locales.get_t(lang).get("annot_someone", "someone") if m.annotate_anon \
        else (m.user.name or m.user.email)
    out = HTMLResponse(
        _inject_web_ui(html, None, can_debate=False, is_owner=False,
                       owner_name=owner_display, lang=lang, annotate=ctx),
        headers=_NO_CACHE,
    )
    if not user and not annot_token:
        out.set_cookie("annot_token", secrets.token_urlsafe(12), max_age=60 * 60 * 24 * 365, samesite="lax")
    return out


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.has_permission("admin") and not user.has_permission("view_course_maps"):
        return RedirectResponse("/app", status_code=302)
    lang = _get_lang(request)
    return templates.TemplateResponse("admin.html", {
        "request":  request,
        "user":     user,
        "is_admin": user.has_permission("admin"),
        "t":        _locales.get_t(lang),
        "lang":     lang,
    })


class UserCreate(BaseModel):
    email:    str
    password: str
    name:     str
    role:     str = "standard"


@app.post("/api/admin/users")
def create_user(body: UserCreate, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    role = db.query(Role).filter(Role.name == body.role).first()
    if not role:
        raise HTTPException(400, f"Role not found: {body.role}")
    u = User(email=body.email, password_hash=hash_password(body.password), name=body.name, role=role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id}


@app.get("/api/admin/users")
def list_users(user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{"id": u.id, "email": u.email, "name": u.name,
             "role": u.role.name if u.role else None, "is_active": u.is_active} for u in users]


@app.put("/api/admin/users/{uid}/role")
def set_role(uid: int, body: dict, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "User not found")
    role = db.query(Role).filter(Role.name == body["role"]).first()
    if not role:
        raise HTTPException(400, f"Role not found: {body['role']}")
    u.role = role
    db.commit()
    return {"ok": True}


@app.put("/api/admin/users/{uid}/active")
def set_active(uid: int, body: dict, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "User not found")
    u.is_active = body["is_active"]
    db.commit()
    return {"ok": True}


class ChangePassword(BaseModel):
    old_password: str
    new_password: str

@app.put("/api/me/password")
def change_own_password(body: ChangePassword, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if not body.new_password.strip():
        raise HTTPException(400, "New password cannot be empty")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@app.put("/api/admin/users/{uid}/password")
def set_password(uid: int, body: dict, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "User not found")
    pw = body.get("password", "").strip()
    if not pw:
        raise HTTPException(400, "Password cannot be empty")
    u.password_hash = hash_password(pw)
    db.commit()
    return {"ok": True}


# ── Courses ───────────────────────────────────────────────────────────────────

@app.get("/api/admin/usage")
def usage_summary(user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    from models import month_start
    from sqlalchemy import func
    rows = (
        db.query(UsageLog.user_id, func.sum(UsageLog.cost_usd), func.sum(UsageLog.tokens_in), func.sum(UsageLog.tokens_out))
        .filter(UsageLog.created_at >= month_start())
        .group_by(UsageLog.user_id)
        .all()
    )
    result = []
    for uid, cost, tin, tout in rows:
        u = db.query(User).filter(User.id == uid).first()
        result.append({
            "user_id": uid,
            "name": u.name if u else "—",
            "email": u.email if u else "—",
            "month_cost_usd": round(float(cost), 5),
            "tokens_in": tin,
            "tokens_out": tout,
            "budget_usd": u.monthly_budget_usd if u else None,
        })
    result.sort(key=lambda x: x["month_cost_usd"], reverse=True)
    return result


@app.delete("/api/admin/users/{uid}")
def delete_user(uid: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    if uid == user.id:
        raise HTTPException(400, "Cannot delete yourself")
    target = db.query(User).filter(User.id == uid).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.role and target.role.name == "admin":
        admin_count = db.query(User).join(User.role).filter(Role.name == "admin", User.is_active == True).count()
        if admin_count <= 1:
            raise HTTPException(400, "Cannot delete the last admin")
    db.query(Map).filter(Map.user_id == uid).delete()
    db.delete(target)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/users/import")
async def import_users_xlsx(
    file: UploadFile = File(...),
    admin: User = Depends(require_permission("admin")),
    db: Session = Depends(get_db),
):
    import io, openpyxl
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(400, "Invalid .xlsx file")
    ws = wb.active

    header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if not header_row:
        raise HTTPException(400, "Empty file")
    headers = [str(h).strip().lower() if h is not None else '' for h in header_row]

    def col(row_vals, name):
        try:
            idx = headers.index(name)
            v = row_vals[idx]
            return str(v).strip() if v is not None else ''
        except ValueError:
            return ''

    all_courses = db.query(Course).all()
    course_map  = {c.name.strip().lower(): c for c in all_courses}
    valid_roles = {r.name for r in db.query(Role).all()}

    created, skipped, errors = [], [], []

    for i, row_vals in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row_vals):
            continue
        name  = col(row_vals, 'name')
        email = col(row_vals, 'email').lower()
        if not email:
            errors.append({'row': i, 'reason': 'Missing email'})
            continue
        if not name:
            errors.append({'row': i, 'reason': 'Missing name'})
            continue
        if db.query(User).filter(User.email == email).first():
            skipped.append(email)
            continue
        password_raw = col(row_vals, 'password')
        auto_pw  = not password_raw
        password = password_raw if password_raw else secrets.token_urlsafe(8)
        role_name = col(row_vals, 'role').lower() or 'standard'
        if role_name not in valid_roles:
            role_name = 'standard'
        role_obj = db.query(Role).filter(Role.name == role_name).first()
        u = User(email=email, password_hash=hash_password(password), name=name, role=role_obj)
        db.add(u)
        db.flush()
        course_name_raw = col(row_vals, 'course')
        enrolled_course = None
        if course_name_raw:
            c = course_map.get(course_name_raw.strip().lower())
            if c:
                c.students.append(u)
                enrolled_course = c.name
        created.append({
            'name':     name,
            'email':    email,
            'password': password if auto_pw else None,
            'course':   enrolled_course,
        })

    db.commit()
    return {'created': created, 'skipped': skipped, 'errors': errors}


class BatchAction(BaseModel):
    ids:    list[int]
    action: str  # "delete" | "activate" | "deactivate"


@app.post("/api/admin/users/batch")
def batch_users(body: BatchAction, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    if body.action not in ("delete", "activate", "deactivate"):
        raise HTTPException(400, "Invalid action")
    errors = []
    for uid in body.ids:
        if body.action == "delete":
            if uid == user.id:
                errors.append(f"Cannot delete yourself (id={uid})")
                continue
            target = db.query(User).filter(User.id == uid).first()
            if not target:
                continue
            if target.role and target.role.name == "admin":
                admin_count = db.query(User).join(User.role).filter(Role.name == "admin", User.is_active == True).count()
                if admin_count <= 1:
                    errors.append(f"Cannot delete the last admin (id={uid})")
                    continue
            db.query(Map).filter(Map.user_id == uid).delete()
            db.delete(target)
        else:
            target = db.query(User).filter(User.id == uid).first()
            if target:
                target.is_active = (body.action == "activate")
    db.commit()
    return {"ok": True, "errors": errors}


@app.put("/api/admin/users/{uid}/budget")
def set_budget(uid: int, body: dict, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "User not found")
    u.monthly_budget_usd = body.get("budget_usd")  # None = no limit
    db.commit()
    return {"ok": True}


@app.get("/api/courses")
def list_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.has_permission("admin"):
        courses = db.query(Course).all()
    elif user.has_permission("view_course_maps"):
        courses = (db.query(Course)
                   .join(course_teachers, Course.id == course_teachers.c.course_id)
                   .filter(course_teachers.c.user_id == user.id)
                   .all())
    else:
        courses = user.courses
    return [{"id": c.id, "name": c.name,
             "teachers": [t.name or t.email for t in c.teachers]} for c in courses]


class CourseCreate(BaseModel):
    name: str


@app.post("/api/courses")
def create_course(body: CourseCreate, user: User = Depends(require_permission("view_course_maps")), db: Session = Depends(get_db)):
    c = Course(name=body.name)
    db.add(c)
    db.flush()
    c.teachers.append(user)
    db.commit()
    db.refresh(c)
    return {"id": c.id}


@app.patch("/api/courses/{course_id}")
def update_course(course_id: int, body: dict, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if "name" in body:
        course.name = body["name"]
    db.commit()
    return {"ok": True}


@app.post("/api/courses/{course_id}/teachers/{uid}")
def add_teacher(course_id: int, uid: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course  = db.query(Course).filter(Course.id == course_id).first()
    teacher = db.query(User).filter(User.id == uid, User.is_active == True).first()
    if not course or not teacher:
        raise HTTPException(404, "Not found")
    if not teacher.has_permission("view_course_maps"):
        raise HTTPException(400, "User does not have teacher permissions")
    if teacher not in course.teachers:
        course.teachers.append(teacher)
        db.commit()
    return {"ok": True}


@app.delete("/api/courses/{course_id}/teachers/{uid}")
def remove_teacher(course_id: int, uid: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course  = db.query(Course).filter(Course.id == course_id).first()
    teacher = db.query(User).filter(User.id == uid).first()
    if not course or not teacher:
        raise HTTPException(404, "Not found")
    if teacher in course.teachers:
        course.teachers.remove(teacher)
        db.commit()
    return {"ok": True}


@app.post("/api/courses/{course_id}/students/{uid}")
def add_student(course_id: int, uid: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course  = db.query(Course).filter(Course.id == course_id).first()
    student = db.query(User).filter(User.id == uid).first()
    if not course or not student:
        raise HTTPException(404, "Not found")
    if student not in course.students:
        course.students.append(student)
        db.commit()
    return {"ok": True}


@app.get("/api/courses/{course_id}")
def get_course(course_id: int, user: User = Depends(require_permission("view_course_maps")), db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if not user.has_permission("admin") and not any(t.id == user.id for t in course.teachers):
        raise HTTPException(403, "Forbidden")
    return {
        "id":       course.id,
        "name":     course.name,
        "teachers": [{"id": t.id, "name": t.name or t.email, "email": t.email} for t in course.teachers],
        "students": [{"id": s.id, "name": s.name, "email": s.email} for s in course.students],
    }


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    db.query(Map).filter(Map.course_id == course_id).update({"course_id": None})
    course.students.clear()
    course.teachers.clear()
    db.flush()
    db.delete(course)
    db.commit()
    return {"ok": True}


@app.get("/api/courses/{course_id}/maps")
def course_maps(course_id: int, user: User = Depends(require_permission("view_course_maps")), db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if not user.has_permission("admin") and not any(t.id == user.id for t in course.teachers):
        raise HTTPException(403, "Forbidden")
    maps = db.query(Map).filter(Map.course_id == course_id).all()
    return [{"id": m.id, "title": m.title, "user": m.user.name,
             "created_at": m.created_at, "updated_at": m.updated_at} for m in maps]


@app.delete("/api/courses/{course_id}/students/{uid}")
def remove_student(course_id: int, uid: int, user: User = Depends(require_permission("admin")), db: Session = Depends(get_db)):
    course  = db.query(Course).filter(Course.id == course_id).first()
    student = db.query(User).filter(User.id == uid).first()
    if not course or not student:
        raise HTTPException(404, "Not found")
    if student in course.students:
        course.students.remove(student)
        db.commit()
    return {"ok": True}


@app.get("/admin/courses/{course_id}", response_class=HTMLResponse)
def course_page(course_id: int, request: Request, session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    user = get_user_or_none(session, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not user.has_permission("view_course_maps"):
        return RedirectResponse("/app", status_code=302)
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if not user.has_permission("admin") and not any(t.id == user.id for t in course.teachers):
        return RedirectResponse("/app", status_code=302)
    lang = _get_lang(request)
    return templates.TemplateResponse("course.html", {
        "request":   request,
        "course_id": course_id,
        "can_admin": user.has_permission("admin"),
        "t":         _locales.get_t(lang),
        "lang":      lang,
    })


# ── Debate-A-Bot ──────────────────────────────────────────────────────────────

def _serialize_map(map_data: dict) -> str:
    nodes = map_data.get("nodes", [])
    steps = map_data.get("steps", [])
    by_type: dict = {}
    for n in nodes:
        by_type.setdefault(n.get("type", "unknown"), []).append(n)
    lines = []
    for n in by_type.get("claim", []):
        lines.append(f"CLAIM: {n.get('content', '')}")
    for label, key in [
        ("NORMATIVE PREMISES",       "normative_premise"),
        ("EMPIRICAL PREMISES",       "empirical_premise"),
        ("METAPHYSICAL COMMITMENTS", "metaphysical_commitment"),
        ("INTERMEDIATE CONCLUSIONS", "intermediate_conclusion"),
    ]:
        items = by_type.get(key, [])
        if items:
            lines.append(f"\n{label}:")
            for n in items:
                lines.append(f"  [{n.get('id','')}] {n.get('content','')}")
                if n.get("notes"):
                    lines.append(f"    notes: {n['notes']}")
    if steps:
        lines.append("\nINFERENTIAL STEPS:")
        for s in steps:
            srcs   = ", ".join(s.get("sources", []))
            tgt    = s.get("target", "")
            rel    = s.get("relation", "supports")
            rule   = s.get("rule", "")
            ann    = s.get("annotation") or {}
            linked = " [linked]" if s.get("linked") else ""
            parts  = [f"{srcs} —[{rel}]→ {tgt}{linked}"]
            if rule:                         parts.append(f"rule: {rule}")
            if ann.get("valid") is False:    parts.append("INVALID")
            if ann.get("fallacy_label"):
                f = ann["fallacy_label"]
                if ann.get("fallacy_reason"): f += f" ({ann['fallacy_reason']})"
                parts.append(f"fallacy: {f}")
            if ann.get("bias_label"):
                b = ann["bias_label"]
                if ann.get("bias_reason"): b += f" ({ann['bias_reason']})"
                parts.append(f"bias: {b}")
            lines.append(f"  {' | '.join(parts)}")
    return "\n".join(lines)


_DEBATE_SYSTEM = {
    "pro": (
        "You are a philosophical debate partner helping a student understand and defend an ethical argument. "
        "The argument map you are working with:\n\n{map_text}\n\n"
        "Your role: defend the central claim. Take its strongest charitable interpretation. "
        "Open with a concise analytical reading (2–3 sentences) identifying the argument's key strengths "
        "and the 1–2 pressure points the student should be ready to defend. "
        "Then engage in Socratic dialogue — ask probing questions to help the student articulate "
        "the argument's foundations more precisely. Keep responses concise (3–6 sentences max unless "
        "asked to elaborate). You are defending the thesis: steelman it. "
        "Respond in the same language as the argument map text above, unless the user explicitly asks you to switch to a different language."
    ),
    "con": (
        "You are a philosophical devil's advocate helping a student stress-test an ethical argument. "
        "The argument map you are working with:\n\n{map_text}\n\n"
        "Your role: attack the central claim. Identify weak premises, logical gaps, "
        "alternative conclusions, and fallacies. "
        "Open with a concise analytical reading (2–3 sentences) identifying the 2–3 most vulnerable "
        "points in the argument — premises that are questionable, steps that are invalid, or assumptions "
        "that are philosophically contentious. "
        "Then engage in Socratic dialogue — press the student to defend the argument's weakest links. "
        "Keep responses concise (3–6 sentences max unless asked to elaborate). "
        "You are opposing the thesis: find its cracks. "
        "Respond in the same language as the argument map text above, unless the user explicitly asks you to switch to a different language."
    ),
}


class DebateRequest(BaseModel):
    messages: list
    mode:     str = "con"


@app.post("/api/maps/{map_id}/debate")
async def debate(map_id: int, body: DebateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    import asyncio, queue, threading
    m = db.query(Map).filter(Map.id == map_id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    if m.user_id != user.id:
        if not user.has_permission("view_course_maps"):
            raise HTTPException(403, "Forbidden")
        course = db.query(Course).filter(Course.id == m.course_id).first()
        if not course or not any(t.id == user.id for t in course.teachers):
            raise HTTPException(403, "Forbidden")

    mode   = body.mode if body.mode in ("pro", "con") else "con"
    system = _DEBATE_SYSTEM[mode].format(map_text=_serialize_map(m.map_data))

    q: queue.Queue = queue.Queue()

    def run():
        try:
            client = _anthropic.Anthropic()
            with client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system,
                messages=body.messages,
            ) as s:
                for text in s.text_stream:
                    q.put({"delta": text})
            q.put({"done": True})
        except Exception as e:
            q.put({"error": str(e)})

    threading.Thread(target=run, daemon=True).start()

    async def event_stream():
        loop = asyncio.get_event_loop()
        while True:
            try:
                msg = await loop.run_in_executor(None, lambda: q.get(timeout=120))
                yield f"data: {json.dumps(msg)}\n\n"
                if "done" in msg or "error" in msg:
                    break
            except Exception:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")
