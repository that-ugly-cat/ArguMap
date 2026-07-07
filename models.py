"""
Database models for AutoMap v2.

ORM: SQLAlchemy with SQLite (single-file DB at ./data/maps.db, persisted via Docker volume).

Permission model:
  Permission (slug) ← role_permissions (M2M) → Role → User
  Roles are seeded once; permissions are checked at runtime via User.has_permission().

Map ownership:
  Map.user_id   — the owner (can save, share, delete)
  Map.course_id — optional link to a Course (teacher can view via view_course_maps permission)
  Map.share_token — nullable UUID; when set, the map is publicly accessible at /share/{token}

Migration strategy: init_db() runs ALTER TABLE for each new column on every startup.
SQLite silently raises on duplicate columns so failures are caught and ignored.
This is intentional but fragile: column type changes are not handled.
"""
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    Table, create_engine, func, select
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = "sqlite:///./data/maps.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ── M2M: role ↔ permission ────────────────────────────────────────────────────

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id",          Integer, ForeignKey("roles.id"),          primary_key=True),
    Column("permission_slug",  String,  ForeignKey("permissions.slug"),  primary_key=True),
)

# ── M2M: user ↔ course (students) ────────────────────────────────────────────

user_courses = Table(
    "user_courses", Base.metadata,
    Column("user_id",   Integer, ForeignKey("users.id"),    primary_key=True),
    Column("course_id", Integer, ForeignKey("courses.id"),  primary_key=True),
)

# ── M2M: course ↔ teacher ─────────────────────────────────────────────────────

course_teachers = Table(
    "course_teachers", Base.metadata,
    Column("course_id", Integer, ForeignKey("courses.id"), primary_key=True),
    Column("user_id",   Integer, ForeignKey("users.id"),   primary_key=True),
)


# ── Permissions ───────────────────────────────────────────────────────────────

class Permission(Base):
    __tablename__ = "permissions"
    slug        = Column(String, primary_key=True)
    description = Column(Text)


# ── Roles ─────────────────────────────────────────────────────────────────────

class Role(Base):
    __tablename__ = "roles"
    id          = Column(Integer, primary_key=True)
    name        = Column(String, unique=True, nullable=False)
    description = Column(Text)
    permissions = relationship("Permission", secondary=role_permissions)


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    email         = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name          = Column(String)
    is_active     = Column(Boolean, default=True)
    role_id            = Column(Integer, ForeignKey("roles.id"))
    monthly_budget_usd = Column(Float, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)

    role    = relationship("Role")
    maps    = relationship("Map", back_populates="user")
    courses = relationship("Course", secondary=user_courses, back_populates="students")

    def has_permission(self, slug: str) -> bool:
        if not self.role:
            return False
        return any(p.slug == slug for p in self.role.permissions)


# ── Courses ───────────────────────────────────────────────────────────────────

class Course(Base):
    __tablename__ = "courses"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, nullable=False)
    teacher_id = Column(Integer, ForeignKey("users.id"))  # legacy; superseded by course_teachers
    created_at = Column(DateTime, default=datetime.utcnow)

    monthly_budget_usd = Column(Float, nullable=True)

    teachers = relationship("User", secondary=course_teachers, backref="taught_courses")
    students = relationship("User", secondary=user_courses, back_populates="courses")
    maps     = relationship("Map", back_populates="course")


# ── Maps ──────────────────────────────────────────────────────────────────────

class Map(Base):
    __tablename__ = "maps"
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id    = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title        = Column(String, nullable=False)
    map_data     = Column(JSON, nullable=False)
    reasoning    = Column(JSON, nullable=True)
    source_text  = Column(Text, nullable=True)
    share_token  = Column(String, nullable=True, unique=True)
    template_id  = Column(Integer, ForeignKey("templates.id"), nullable=True)
    # Annotation layer (#3): stable public link + open/frozen flag. The layer
    # itself lives in the annotations table, never in map_data.
    annotate_token = Column(String, nullable=True, unique=True)
    annotate_open  = Column(Boolean, default=False)
    annotate_anon  = Column(Boolean, default=False)  # hide the owner's name from annotators
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user   = relationship("User", back_populates="maps")
    course = relationship("Course", back_populates="maps")


# ── Guided templates ──────────────────────────────────────────────────────────

class Template(Base):
    """A teacher-authored guided-construction scaffold.

    A student who opens the template's link gets a personal Map instance
    (one per student+template, idempotent) seeded from `claim`, and lands in
    guided mode. `claim` may contain a single [PLACEHOLDER] the student fills in.
    `slots` (optional) holds preset option-lists for premise choice-slots (#5),
    e.g. {"empirical": {"options": [...], "correct": 1}}.
    """
    __tablename__ = "templates"
    id         = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id  = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title      = Column(String, nullable=False)
    claim      = Column(Text, nullable=False)
    slots      = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("User")
    course  = relationship("Course")


# ── Annotation layer (#3) ──────────────────────────────────────────────────────

class AnnotationSession(Base):
    """A round of annotation over a map. Only one is active per map at a time;
    opening a new session archives the previous (is_active=False), giving a clean
    layer while preserving history (RoomPulse's run model)."""
    __tablename__ = "annotation_sessions"
    id         = Column(Integer, primary_key=True)
    map_id     = Column(Integer, ForeignKey("maps.id"), nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Annotation(Base):
    """A single annotation on a node or edge, scoped to a session. Lives entirely
    separate from Map.map_data — never serialized into the map itself."""
    __tablename__ = "annotations"
    id             = Column(Integer, primary_key=True)
    session_id     = Column(Integer, ForeignKey("annotation_sessions.id"), nullable=False)
    map_id         = Column(Integer, ForeignKey("maps.id"), nullable=False)
    target_kind    = Column(String, nullable=False)    # 'node' | 'edge'
    target_id      = Column(String, nullable=False)     # id of the node/edge in the map
    author_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_token   = Column(String, nullable=True)      # anonymous identity when not logged in
    author_name    = Column(String, nullable=True)
    kind           = Column(String, nullable=False)     # 'comment' | 'plausibility' | 'fallacy' | 'bias'
    payload        = Column(JSON, nullable=True)         # {text} | {value:1..5} | {label, reason}
    status         = Column(String, default="visible")   # 'visible' | 'hidden' (moderation)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── App config (key-value settings) ────────────────────────────────────────────

class AppConfig(Base):
    """Global key-value settings editable by admins at runtime.

    Used for self-service registration: `registration_open` ('1'/'0') gates the
    public /register route, and `welcome_map_id` names the map cloned into each
    new account (empty = new users start with no maps)."""
    __tablename__ = "app_config"
    key   = Column(String, primary_key=True)
    value = Column(String, nullable=True)


DEFAULT_CONFIG = {
    "registration_open": "0",
    "welcome_map_id":    "",
}


def get_config(db, key: str, default: str | None = None) -> str | None:
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    return row.value if row else DEFAULT_CONFIG.get(key, default)


def set_config(db, key: str, value: str) -> None:
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppConfig(key=key, value=value))
    db.commit()


# ── Usage log ─────────────────────────────────────────────────────────────────

# Pricing per million tokens (input, output) — update when Anthropic changes rates
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0,  15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-5":  (0.8,   4.0),
}

def calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    p = PRICING.get(model, PRICING["claude-sonnet-4-6"])
    return (tokens_in * p[0] + tokens_out * p[1]) / 1_000_000


class UsageLog(Base):
    __tablename__ = "usage_log"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    feature    = Column(String, nullable=False)   # 'pipeline', 'debate'
    model      = Column(String, nullable=False)
    tokens_in  = Column(Integer, nullable=False)
    tokens_out = Column(Integer, nullable=False)
    cost_usd   = Column(Float,   nullable=False)
    map_id     = Column(Integer, ForeignKey("maps.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    map  = relationship("Map")


# ── Seed data ─────────────────────────────────────────────────────────────────

SEED_PERMISSIONS = [
    ("manual",           "Manual map editor"),
    ("pipeline",         "LLM automapping pipeline"),
    ("debate",           "Debate-A-Bot chat"),
    ("compare",          "Map comparison"),
    ("view_course_maps", "View all maps in own courses (teacher)"),
    ("admin",            "Admin panel access"),
]

SEED_ROLES = [
    ("basic",    "Manual editor only",              ["manual"]),
    ("standard", "Manual + pipeline",               ["manual", "pipeline"]),
    ("full",     "All student features",            ["manual", "pipeline", "debate"]),
    ("teacher",  "Teacher: full + course overview", ["manual", "pipeline", "debate", "view_course_maps"]),
    ("admin",    "Full access",                     ["manual", "pipeline", "debate", "compare", "view_course_maps", "admin"]),
]


def init_db():
    Base.metadata.create_all(bind=engine)
    # Additive migrations: each ALTER TABLE is attempted on every startup.
    # SQLite raises OperationalError on duplicate columns, which we catch and ignore.
    # Add new columns here; never remove or rename — that requires a manual migration.
    from sqlalchemy import text
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE maps ADD COLUMN reasoning JSON",
            "ALTER TABLE maps ADD COLUMN source_text TEXT",
            "ALTER TABLE maps ADD COLUMN share_token TEXT",
            "ALTER TABLE maps ADD COLUMN template_id INTEGER",
            "ALTER TABLE maps ADD COLUMN annotate_token TEXT",
            "ALTER TABLE maps ADD COLUMN annotate_open BOOLEAN DEFAULT 0",
            "ALTER TABLE maps ADD COLUMN annotate_anon BOOLEAN DEFAULT 0",
            # course_teachers junction table (idempotent)
            """CREATE TABLE IF NOT EXISTS course_teachers (
                course_id INTEGER NOT NULL REFERENCES courses(id),
                user_id   INTEGER NOT NULL REFERENCES users(id),
                PRIMARY KEY (course_id, user_id)
            )""",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass
        # Migrate legacy teacher_id values into the junction table
        try:
            conn.execute(text(
                "INSERT OR IGNORE INTO course_teachers (course_id, user_id) "
                "SELECT id, teacher_id FROM courses WHERE teacher_id IS NOT NULL"
            ))
            conn.commit()
        except Exception:
            pass
    db = SessionLocal()
    try:
        if db.query(Permission).count() == 0:
            for slug, desc in SEED_PERMISSIONS:
                db.add(Permission(slug=slug, description=desc))
            db.flush()
        if db.query(Role).count() == 0:
            for name, desc, slugs in SEED_ROLES:
                perms = db.query(Permission).filter(Permission.slug.in_(slugs)).all()
                db.add(Role(name=name, description=desc, permissions=perms))
        for key, value in DEFAULT_CONFIG.items():
            if db.query(AppConfig).filter(AppConfig.key == key).first() is None:
                db.add(AppConfig(key=key, value=value))
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def month_start() -> datetime:
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def user_month_cost(db, user_id: int) -> float:
    result = db.execute(
        select(func.coalesce(func.sum(UsageLog.cost_usd), 0.0))
        .where(UsageLog.user_id == user_id)
        .where(UsageLog.created_at >= month_start())
    ).scalar()
    return float(result)


def log_usage(db, *, user_id: int, feature: str, model: str,
              tokens_in: int, tokens_out: int, map_id: int | None = None) -> float:
    cost = calc_cost(model, tokens_in, tokens_out)
    db.add(UsageLog(
        user_id=user_id, feature=feature, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost, map_id=map_id,
    ))
    db.commit()
    return cost
