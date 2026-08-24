"""
Authentication for AutoMap v2.

Strategy: JWT stored in an httpOnly cookie named 'session'.
- Token lifetime: EXPIRE_DAYS days (renewed on each login, not on activity).
- Secret key must be set via JWT_SECRET env var; startup will crash if missing.
- `get_current_user` is the standard FastAPI dependency for protected API routes.
- `get_user_or_none` is used by HTML routes that redirect manually instead of raising 401.
- `require_permission(slug)` is a dependency factory for permission-gated routes.
"""
import ipaddress
import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from models import Role, User, clone_welcome_map, get_db

log = logging.getLogger("argumap.auth")

SECRET_KEY  = os.environ["JWT_SECRET"]
ALGORITHM   = "HS256"
EXPIRE_DAYS = 7

# ── Two modes ─────────────────────────────────────────────────────────────────
#
#   local     (default)   email + password against the users table
#   gateway               an upstream SSO gate vouches via X-Borant-*
#
# `local` is the default and that is not negotiable: an app that believes an
# identity header with no gate in front of it lets anyone be anyone.
#
# **The rule this app is the reason for.** The pipeline spends on the server's
# Anthropic key, and `monthly_budget_usd = None` means *no ceiling at all* —
# `_check_budget` returns immediately on None. So a profile created from a
# header gets DEFAULT_ROLE and nothing else: `basic`, which has no `pipeline`
# permission and therefore cannot open the tap. Promotion to `full` or
# `teacher` stays a human click in /admin. This lives in code and not in
# configuration on purpose: a role that spends must not be one typo away.
AUTH_MODE = os.environ.get("AUTH_MODE", "local").strip().lower()
DEFAULT_ROLE = "basic"

# I ruoli che possono far girare la pipeline, cioe' spendere sulla chiave
# Anthropic del server. Sono tutti tranne `basic`: il permesso si chiama
# `pipeline` e ce l'hanno standard, full, teacher e admin.
RUOLI_CHE_SPENDONO = {"standard", "full", "teacher", "admin"}

# Il tetto mensile che riceve un profilo nato dal gate. `None` non significa
# zero, significa **nessun limite**: `_check_budget` con None torna subito. Le
# righe esistenti hanno 200 dal 24/8/2026, e un profilo nuovo che nascesse
# senza tetto sarebbe l'unico del parco a poter spendere senza fondo.
TETTO_PREDEFINITO_USD = float(os.environ.get("ARGUMAP_DEFAULT_BUDGET_USD", "200"))

TRUSTED_PROXY = os.environ.get("BORANT_TRUSTED_PROXY", "127.0.0.1")
BORANT_LOGOUT_URL = os.environ.get("BORANT_LOGOUT_URL", "https://id.borant.eu/logout")


def _parse_trusted(raw: str) -> list:
    nets = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            log.warning("BORANT_TRUSTED_PROXY: ignoring %r, not an address or CIDR", chunk)
    return nets


TRUSTED_PROXIES = _parse_trusted(TRUSTED_PROXY)


def gateway_mode() -> bool:
    return AUTH_MODE == "gateway"


def _from_trusted_proxy(request: Request) -> bool:
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_PROXIES)


def user_from_gateway(request: Request, db: Session) -> User | None:
    """The user the gate vouched for, or None.

    Lookup is by `borant_sub` and never by email: one typo in the gate's admin
    panel must not hand one person another person's maps. Note that in this app
    the same human legitimately holds more than one local row under different
    addresses, which is precisely why the linking is a script written by hand.
    """
    if not gateway_mode():
        return None
    sub = request.headers.get("x-borant-sub")
    if not sub:
        return None
    if not _from_trusted_proxy(request):
        log.warning("X-Borant-Sub from %s, outside BORANT_TRUSTED_PROXY (%s): ignored",
                    request.client.host if request.client else "?", TRUSTED_PROXY)
        return None

    user = db.query(User).filter(User.borant_sub == sub).first()
    if user is not None:
        return user if user.is_active else None

    email = (request.headers.get("x-borant-email", "") or f"{sub}@borant.invalid").strip().lower()
    taken = db.query(User).filter(User.email == email).first()
    if taken is not None:
        # Qualcuno con questo indirizzo c'e' gia' e non e' legato. NON si adotta
        # quella riga: qui una persona sola ha piu' righe sotto indirizzi
        # diversi, quindi indovinare sarebbe sbagliato piu' spesso che altrove.
        log.error("gateway: %s arrives as %s, but a local row already holds that "
                  "address and has no borant_sub. Run "
                  "`python map_borant.py --map %s=%s` instead of letting the gate guess.",
                  email, sub, email, sub)
        return None

    # L'hint del gate propone il ruolo di partenza, e da oggi viene onorato.
    #
    # Il §18 nasce proprio da qui e dice di non provisionare mai da un header un
    # ruolo che spende. La deroga e' deliberata e regge sullo stesso
    # presupposto di Grant Radar e RoomPulse: quella regola presume la
    # **registrazione aperta**, dove l'hint porta cio' che ha chiesto *chi
    # bussa*. Su Borant ID e' spenta, e anche una richiesta d'accesso fa
    # scegliere il ruolo all'amministratore approvando — quindi qui `teacher` o
    # `full` ci sono solo perche' un umano li ha digitati.
    #
    # Quello che il codice deve comunque e' **rumore**, e un tetto di spesa.
    hint = (request.headers.get("x-borant-hint", "") or "").strip().lower()
    nome_ruolo = DEFAULT_ROLE
    if hint:
        if db.query(Role).filter(Role.name == hint).first() is not None:
            nome_ruolo = hint
        else:
            log.warning("gateway: hint %r non e' un ruolo di questa app, ricado su %r",
                        hint, DEFAULT_ROLE)

    role = db.query(Role).filter(Role.name == nome_ruolo).first()
    if role is None:
        log.error("gateway: role %r missing, refusing to create a profile with no role",
                  nome_ruolo)
        return None
    if nome_ruolo in RUOLI_CHE_SPENDONO:
        log.warning(
            "gateway: %s (%s) creato come %r su suggerimento del gate. Quel ruolo "
            "puo' far girare la pipeline, che paga dalla chiave del server. Tetto "
            "mensile impostato a %.2f USD. Revocare da /admin se non era voluto.",
            email, sub, nome_ruolo, TETTO_PREDEFINITO_USD)

    user = User(email=email,
                name=request.headers.get("x-borant-name", "").strip() or None,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role=role, borant_sub=sub, is_active=True,
                monthly_budget_usd=TETTO_PREDEFINITO_USD)
    db.add(user)
    db.commit()
    db.refresh(user)
    # Stessa cortesia che riceve chi si registra da se': senza questa riga un
    # profilo nato dal gate apre un'app vuota, e non ha modo di sapere che la
    # mappa di benvenuto esiste. Non e' decorazione — e' la differenza fra
    # «ecco come si fa» e uno schermo bianco al primo accesso.
    clone_welcome_map(db, user.id)
    log.info("gateway: new profile for %s (%s) as %s, tetto %.2f USD",
             email, sub, nome_ruolo, TETTO_PREDEFINITO_USD)
    return user

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


# ── Dependencies ──────────────────────────────────────────────────────────────

def get_current_user(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if gateway_mode():
        # L'header vince sul cookie locale, sempre, e non c'e' ripiego.
        user = user_from_gateway(request, db)
        if user is not None:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = _decode_token(session)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_user_or_none(session: str | None, db: Session,
                     request: Request | None = None) -> User | None:
    """Returns the authenticated user or None — for HTML routes that redirect manually.

    In `gateway` the identity lives in the headers, so the request has to come
    in too; without it this returns None, which fails closed."""
    if gateway_mode():
        return user_from_gateway(request, db) if request is not None else None
    if not session:
        return None
    try:
        user_id = _decode_token(session)
    except HTTPException:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def require_permission(slug: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if not user.has_permission(slug):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission required: {slug}")
        return user
    return _check
