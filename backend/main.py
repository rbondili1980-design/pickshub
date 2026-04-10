"""
SharpSlips — FastAPI backend

Changes in this file:
  T1  Backend WS batch queue: _pick_batch_queue + _flush_batch() + _flush_batch_loop()
      new_pick events are queued and flushed every 2 s as a single pick_batch message.
      Scrape lifecycle events (scrape_started, scrape_done, otp_*) still broadcast immediately.
  T2  CORS: reads CORS_ORIGINS or ALLOWED_ORIGINS env var; defaults include localhost:5173
      and localhost:3000.  Startup env-validation now prints a clear error and exits with
      code 1 rather than raising RuntimeError.  Non-secret vars are logged at startup.
  T3  Scraper retry + isolation: _run_with_retry() wraps each scraper; both run concurrently
      via asyncio.gather() so one failure never aborts the other.
  T4  Structured logging via loguru: console + rotating file (logs/app.log).
      Request/response timing logged via HTTP middleware.
      WS connect/disconnect and batch-flush events logged.
"""
import asyncio
import math
import os
import secrets
import sys
import time
import zoneinfo as _zi
from datetime import datetime, date, timedelta
from pathlib import Path

_EST = _zi.ZoneInfo("America/New_York")

from dotenv import load_dotenv

# Explicit path so the service works regardless of CWD
load_dotenv(Path(__file__).parent / ".env")

# ── T4: loguru setup (before anything else logs) ─────────────────────────────
from loguru import logger

_LOGS_DIR = Path(__file__).parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

logger.remove()  # remove default stderr handler
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> <level>{level:<8}</level> {name} — {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    str(_LOGS_DIR / "app.log"),
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} {level:<8} {name} — {message}",
)

# ── T2: Startup env validation ────────────────────────────────────────────────
_REQUIRED_ENV = ["GROQ_API_KEY"]
_missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
if _missing:
    for k in _missing:
        logger.error(f"Missing required env var: {k}")
    sys.exit(1)  # clear message + non-zero exit; does not raise so logs flush first

# Log non-secret env vars at startup for visibility
def _mask(key: str, val: str) -> str:
    """Return last-4 of secret values, full value for non-secrets."""
    _secrets = {"GROQ_API_KEY", "ACTION_NETWORK_PASSWORD", "ADMIN_PASS"}
    if key in _secrets:
        return f"***{val[-4:]}" if val else "MISSING"
    return val or "(not set)"

_ENV_DISPLAY = [
    "GROQ_API_KEY", "ACTION_NETWORK_EMAIL", "ACTION_NETWORK_PASSWORD",
    "ADMIN_USER", "ADMIN_PASS", "CORS_ORIGINS", "ALLOWED_ORIGINS", "DATABASE_URL",
]

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, distinct, func, or_, select

from auth import require_auth, require_admin, get_role, authenticate, create_token, decode_token
from models import Pick, AppConfig, SessionLocal, init_db

# SCRAPER_ENABLED=false on Fly.io (API-only, no Playwright)
# SCRAPER_ENABLED=true  on Mac   (full scraping mode)
_SCRAPER_ENABLED = os.getenv("SCRAPER_ENABLED", "true").lower() == "true"

# Safe imports — pure Python, no Playwright
from scrapers.pick_utils import detect_bet_scope, parse_player_prop
from scrapers.scrape_state import get_last_scraped, set_last_scraped

# Playwright-dependent imports — lazy loaded only when scraping is enabled
if _SCRAPER_ENABLED:
    from scrapers.action_network import run_scrape as scrape_an
    from scrapers.vsin_splits import fetch_all_splits
    from scrapers.winible import run_scrape as scrape_winible
    from scrapers.auto_grader import run_grader

# ── Splits cache ──────────────────────────────────────────────────────────────
_splits_cache: dict = {}
_splits_refreshed_at: str | None = None
_SPLITS_REFRESH_INTERVAL = 300  # seconds

# ── Auto-scrape schedule ───────────────────────────────────────────────────────
_AUTO_SCRAPE_INTERVAL = int(os.getenv("AUTO_SCRAPE_INTERVAL", "1800"))  # default 30 min
_AUTO_GRADE_INTERVAL = int(os.getenv("AUTO_GRADE_INTERVAL", "1800"))   # default 30 min


async def _refresh_splits_cache():
    global _splits_cache, _splits_refreshed_at
    try:
        _splits_cache = await fetch_all_splits()
        _splits_refreshed_at = datetime.utcnow().strftime("%H:%M UTC")
        total_games = sum(len(v) for v in _splits_cache.values())
        logger.info(f"Splits cache refreshed — {total_games} games across {len(_splits_cache)} dates")
    except Exception as e:
        logger.error(f"Splits cache refresh failed: {e}")


async def _splits_refresh_loop():
    while True:
        await _refresh_splits_cache()
        await asyncio.sleep(_SPLITS_REFRESH_INTERVAL)


# ── T2: App + CORS ────────────────────────────────────────────────────────────
app = FastAPI(
    docs_url=None,    # disable /docs in production
    redoc_url=None,   # disable /redoc in production
    openapi_url=None, # disable /openapi.json — don't expose API schema publicly
)

# Accept either CORS_ORIGINS (task spec) or ALLOWED_ORIGINS (existing .env.example).
_cors_raw = os.getenv("CORS_ORIGINS") or os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://localhost:3000",
]
# allow_credentials=True is incompatible with wildcard origin in CORS spec
_allow_credentials = _allowed_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers + server info removal ────────────────────────────────────
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]      = "geolocation=(), camera=(), microphone=()"
    # Remove server info that reveals stack
    for h in ("server", "x-powered-by"):
        if h in response.headers:
            del response.headers[h]
    return response


# ── Body size limit (1 MB max) ────────────────────────────────────────────────
_MAX_BODY = 1 * 1024 * 1024  # 1 MB

@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


# ── Endpoint-level rate limiter (scrape / grade) ──────────────────────────────
_endpoint_hits: dict[str, list[float]] = {}
_ENDPOINT_LIMITS = {
    "/api/scrape": (2,  5 * 60),   # 2 calls per 5 min
    "/api/grade":  (2,  5 * 60),   # 2 calls per 5 min
}

def _check_endpoint_rate(ip: str, path: str) -> bool:
    """Returns True if request is within rate limit, False if exceeded."""
    if path not in _ENDPOINT_LIMITS:
        return True
    max_calls, window = _ENDPOINT_LIMITS[path]
    key = f"{ip}:{path}"
    now = time.monotonic()
    _endpoint_hits.setdefault(key, [])
    _endpoint_hits[key] = [t for t in _endpoint_hits[key] if now - t < window]
    if len(_endpoint_hits[key]) >= max_calls:
        return False
    _endpoint_hits[key].append(now)
    return True


# ── T4: HTTP request/response logging middleware ──────────────────────────────
@app.middleware("http")
async def _log_requests(request: Request, call_next):
    from fastapi.responses import JSONResponse as _JR
    ip = request.client.host if request.client else "unknown"
    if not _check_endpoint_rate(ip, request.url.path):
        return _JR(status_code=429, content={"detail": "Too many requests — try again later"})
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} ({elapsed_ms:.0f}ms)"
    )
    return response


# ── T1: WebSocket batch queue ─────────────────────────────────────────────────
_clients: list[WebSocket] = []
_pick_batch_queue: list[dict] = []     # accumulates new_pick payloads between flushes
_BATCH_INTERVAL = 2.0                  # seconds between batch flushes


async def broadcast(data: dict):
    """Send a message immediately to all connected WS clients (used for lifecycle events)."""
    dead = []
    for ws in _clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.remove(ws)


async def _flush_batch():
    """
    Send all queued new_pick payloads as a single pick_batch message.
    Called every _BATCH_INTERVAL seconds by _flush_batch_loop().
    A pick_batch message has shape: {type: "pick_batch", picks: [...]}
    The frontend merges these in one setState call → single re-render per batch.
    """
    global _pick_batch_queue
    if not _pick_batch_queue:
        return
    batch = _pick_batch_queue
    _pick_batch_queue = []
    await broadcast({"type": "pick_batch", "picks": batch})
    logger.info(f"WS batch flushed — {len(batch)} pick(s) sent to {len(_clients)} client(s)")


async def _flush_batch_loop():
    """Background task: flush the pick batch queue every _BATCH_INTERVAL seconds."""
    while True:
        await asyncio.sleep(_BATCH_INTERVAL)
        await _flush_batch()


def _seconds_until_next_scrape_slot() -> float:
    """
    Schedule (all times in US/Eastern):
      10:00 AM – 10:00 PM EST  → every AUTO_SCRAPE_INTERVAL seconds (peak, default 10 min)
      10:00 PM – 10:00 AM EST  → every 2 hours (overnight, low-activity)

    Slots snap to fixed clock boundaries for predictability.
    """
    now = datetime.now(_EST)
    hour = now.hour  # 0–23 in Eastern time

    peak_interval_min = _AUTO_SCRAPE_INTERVAL // 60   # e.g. 10
    overnight_interval_min = 120                       # always 2 hours overnight

    # Peak window: 10 AM (10) to 10 PM (22)
    if 10 <= hour < 22:
        interval_min = peak_interval_min
    else:
        interval_min = overnight_interval_min

    minute = hour * 60 + now.minute
    elapsed = minute % interval_min
    remaining_min = interval_min - elapsed if elapsed > 0 else interval_min
    remaining_sec = remaining_min * 60 - now.second

    return max(remaining_sec, 1.0)


async def _auto_scrape_loop():
    """
    Background task: scrapes on a time-aware schedule and is sleep-safe.

    Schedule:
      00:00 – 11:59  → every 60 minutes  (overnight / low-activity window)
      12:00 – 23:59  → every 30 minutes  (peak picks window)

    Sleep-safety:
      After each asyncio.sleep(), we measure the ACTUAL elapsed wall-clock time.
      If the Mac slept and woke up, asyncio.sleep() completes immediately but
      actual_elapsed >> expected_sleep.  We detect this and trigger a scrape
      right away instead of waiting for the next slot boundary, ensuring we never
      silently miss hours of picks when the laptop wakes from sleep.

    Startup catch-up:
      On startup, if the checkpoint shows the last scrape was more than one slot
      ago, we fire immediately (no 10 s delay) so a reboot never causes a gap.
    """
    from scrapers.scrape_state import get_last_scraped as _get_last
    from datetime import timezone as _tz

    # ── Startup catch-up: check how long since last successful scrape ─────────
    last_scraped = _get_last("winible") or _get_last("action_network")
    max_interval = 60 * 60  # 1 hour worst case
    if last_scraped:
        gap = (datetime.now(_tz.utc) - last_scraped).total_seconds()
        if gap > max_interval:
            logger.info(f"Auto-scrape: {gap/60:.0f} min since last scrape — running immediately (no 10s delay)")
        else:
            logger.info(f"Auto-scrape: last scrape {gap/60:.1f} min ago — warming up 10s")
            await asyncio.sleep(10)
    else:
        # First ever run — warm up briefly
        await asyncio.sleep(10)

    while True:
        global _scraping, _scrape_started_at
        now = datetime.now()

        # Release stale lock (Mac woke mid-scrape; Playwright task is likely dead)
        if _scraping and _scrape_started_at and time.monotonic() - _scrape_started_at > _SCRAPE_TIMEOUT:
            logger.warning("Auto-scrape: releasing stale scrape lock before slot fire")
            _scraping = False

        if _scraping:
            logger.info("Auto-scrape: skipping slot — scrape already in progress")
        else:
            logger.info(
                f"Auto-scrape: starting scheduled scrape at {now.strftime('%H:%M')} (source=all)"
            )
            _scraping = True
            _scrape_started_at = time.monotonic()
            asyncio.create_task(_do_scrape("all"))

        sleep_sec = _seconds_until_next_scrape_slot()
        # Add ±5 min jitter so requests don't hit at exactly the same clock time
        # every cycle — predictable intervals are a strong bot detection signal.
        import random as _random
        jitter = _random.randint(-300, 300)
        sleep_sec = max(60, sleep_sec + jitter)
        logger.info(
            f"Auto-scrape: next slot in {sleep_sec:.0f}s (jitter {jitter:+d}s, "
            f"{'60-min' if now.hour < 12 else '30-min'} window)"
        )

        # ── Sleep, then check if Mac woke from sleep ──────────────────────────
        t0 = time.monotonic()
        await asyncio.sleep(sleep_sec)
        actual_elapsed = time.monotonic() - t0

        if actual_elapsed > sleep_sec + 120:
            # Mac (or system) was suspended — woke up after a long gap.
            # The next loop iteration will fire a scrape immediately.
            gap_min = (actual_elapsed - sleep_sec) / 60
            logger.info(
                f"Auto-scrape: wake-from-sleep detected (extra {gap_min:.0f} min gap) "
                f"— triggering immediate catch-up scrape"
            )


async def _auto_grade_loop():
    """
    Background task: auto-grade ungraded picks every _AUTO_GRADE_INTERVAL seconds.
    Offset by 15 minutes from the scrape loop so grading runs after new picks land.
    Invalidates the stats cache after each grading run that changes any pick.
    """
    # Wait 15 min initially so the first scrape can finish before we try to grade
    await asyncio.sleep(900)
    while True:
        global _stats_cache
        logger.info("Auto-grader: starting grading run")
        try:
            result = await run_grader()
            if result.get("graded", 0) > 0:
                _stats_cache = None  # invalidate so Tracker/Dashboard reflect new results
                logger.info(f"Auto-grader: {result['graded']} picks graded — stats cache cleared")
        except Exception as e:
            logger.error(f"Auto-grader loop error: {e}")
        await asyncio.sleep(_AUTO_GRADE_INTERVAL)


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("DB connected — tables ready")
    logger.info(f"Mode: {'FULL (scraper + API)' if _SCRAPER_ENABLED else 'API-ONLY (no scraper)'}")
    asyncio.create_task(_flush_batch_loop())
    logger.info(f"WS batch queue started (flush every {_BATCH_INTERVAL}s)")
    if _SCRAPER_ENABLED:
        asyncio.create_task(_splits_refresh_loop())
        logger.info("Splits cache loop started")
        asyncio.create_task(_auto_scrape_loop())
        peak_min = _AUTO_SCRAPE_INTERVAL // 60
        logger.info(f"Auto-scrape loop started (10AM–10PM EST → {peak_min}-min, 10PM–10AM EST → 120-min)")
        asyncio.create_task(_auto_grade_loop())
        logger.info(f"Auto-grader loop started (every {_AUTO_GRADE_INTERVAL}s)")
    # T2: log env var state (mask secrets)
    logger.info("Env vars validated:")
    for k in _ENV_DISPLAY:
        v = os.getenv(k, "")
        if v:  # only log vars that are actually set
            logger.info(f"  {k} = {_mask(k, v)}")
    logger.info(f"CORS origins: {_allowed_origins}")
    logger.info("SharpSlips backend started")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = ""):
    """
    WebSocket endpoint. Requires ?token=<jwt> query param.
    Validates the JWT before accepting the connection.
    """
    authenticated = False
    if token:
        try:
            decode_token(token)   # raises HTTPException if invalid/expired
            authenticated = True
        except Exception:
            pass

    if not authenticated:
        await websocket.close(code=4001)
        logger.warning("WS rejected — invalid or missing JWT token")
        return

    await websocket.accept()
    _clients.append(websocket)
    logger.info(f"WS client connected — {len(_clients)} total")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _clients:
            _clients.remove(websocket)
        logger.info(f"WS client disconnected — {len(_clients)} remaining")


# ── Picks API ─────────────────────────────────────────────────────────────────

def _row(p: Pick) -> dict:
    return {
        "id":          p.id,
        "source":      p.source,
        "expert":      p.expert,
        "record":      p.record,
        "pick":        p.pick,
        "game":        p.game,
        "odds":        p.odds,
        "sport":       p.sport,
        "units":       p.units,
        "comment":     p.comment,
        "pick_type":   p.pick_type,
        "user_note":   p.user_note,
        # game-segment scope
        "bet_scope":   p.bet_scope,
        # player prop fields
        "player_name": p.player_name,
        "stat_type":   p.stat_type,
        "stat_line":   p.stat_line,
        "over_under":  p.over_under,
        # grading / edge — edge_score reserved for ML model
        "result":      p.result,
        "edge_score":  p.edge_score,
        # visibility — hidden picks suppressed from public feed
        "hidden":      bool(p.hidden),
        "session_id":  p.session_id,
        "posted_at":   p.posted_at,
        "scraped_at":  p.scraped_at.isoformat() + "Z" if p.scraped_at else None,
    }


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def login(body: LoginBody, request: Request):
    """
    Exchange username + password for a signed JWT token.
    Returns {token, role, username} on success.
    Rate-limited: 5 failures per IP per 15 min → 429.
    """
    ip = request.client.host if request.client else "unknown"
    username, role = authenticate(body.username, body.password, ip)
    token = create_token(username, role)
    logger.info(f"Login: {username} ({role}) from {ip}")
    return {"token": token, "role": role, "username": username}


@app.get("/api/me")
async def me(role: str = Depends(get_role)):
    """Return the authenticated user's role (admin or guest)."""
    return {"role": role}


@app.get("/api/picks")
async def get_picks(
    _: str = Depends(require_auth),
    source: str | None = None,
    date: str | None = None,
    expert: str | None = None,
    sport: str | None = None,
    search: str | None = None,
    page: int = 1,
    limit: int = 2000,
    per_page: int | None = None,   # backward-compat alias for limit
    admin: bool = False,           # admin=true returns hidden picks too
):
    """
    Returns paginated picks with optional server-side filtering and full-text search.
    Response shape: {picks, meta: {total, page, limit, pages}}
    Hidden picks are excluded from public responses; pass admin=true to see all.
    """
    actual_limit = per_page if per_page is not None else limit
    async with SessionLocal() as db:
        q = select(Pick).order_by(Pick.posted_at.desc(), Pick.id.desc())

        # Public feed never sees hidden picks
        if not admin:
            q = q.where(or_(Pick.hidden == False, Pick.hidden == None))

        if source: q = q.where(Pick.source == source)
        if date:   q = q.where(Pick.posted_at == date)
        if expert: q = q.where(Pick.expert == expert)
        if sport:  q = q.where(Pick.sport == sport)
        if search:
            term = f"%{search}%"
            q = q.where(
                or_(
                    Pick.pick.ilike(term),
                    Pick.expert.ilike(term),
                    Pick.game.ilike(term),
                    Pick.player_name.ilike(term),
                    Pick.comment.ilike(term),
                )
            )

        total = await db.scalar(select(func.count()).select_from(q.subquery()))
        pages = math.ceil(total / actual_limit) if total else 1
        q = q.offset((page - 1) * actual_limit).limit(actual_limit)
        rows = (await db.execute(q)).scalars().all()

    return {
        "picks": [_row(r) for r in rows],
        "meta": {
            "total": total,
            "page":  page,
            "limit": actual_limit,
            "pages": pages,
        },
    }


# ── Stats TTL cache ───────────────────────────────────────────────────────────
_stats_cache: dict | None = None
_stats_cache_at: float    = 0.0
_STATS_TTL                = 300.0   # 5 minutes


@app.get("/api/stats/summary")
async def get_stats_summary(_: str = Depends(require_auth)):
    """
    Aggregate stats for Dashboard stat cards and charts.
    Response: {total_picks, today_count, experts, by_sport, by_type, avg_odds, edge_distribution}
    Cached in-memory for _STATS_TTL seconds to avoid repeated full-table scans.
    """
    global _stats_cache, _stats_cache_at
    now = time.monotonic()
    if _stats_cache and (now - _stats_cache_at) < _STATS_TTL:
        return _stats_cache

    # Use Eastern time to match scraper's posted_at values
    today = datetime.now(_EST).date().isoformat()
    async with SessionLocal() as db:
        total         = await db.scalar(select(func.count(Pick.id)))
        today_count   = await db.scalar(select(func.count(Pick.id)).where(Pick.posted_at == today))
        experts_count = await db.scalar(select(func.count(distinct(Pick.expert))))

        sport_rows = (await db.execute(
            select(Pick.sport, func.count(Pick.id))
            .where(Pick.sport.isnot(None))
            .group_by(Pick.sport)
            .order_by(func.count(Pick.id).desc())
        )).all()
        by_sport = {r[0]: r[1] for r in sport_rows}

        type_rows = (await db.execute(
            select(Pick.pick_type, func.count(Pick.id))
            .where(Pick.pick_type.isnot(None))
            .group_by(Pick.pick_type)
            .order_by(func.count(Pick.id).desc())
        )).all()
        by_type = {r[0]: r[1] for r in type_rows}

        odds_vals = (await db.execute(
            select(Pick.odds).where(Pick.odds.isnot(None))
        )).scalars().all()
        valid_odds: list[float] = []
        for o in odds_vals:
            try:
                valid_odds.append(float(o))
            except (ValueError, TypeError):
                pass
        avg_odds = round(sum(valid_odds) / len(valid_odds)) if valid_odds else None

    result = {
        "total_picks":       total or 0,
        "today_count":       today_count or 0,
        "experts":           experts_count or 0,
        "by_sport":          by_sport,
        "by_type":           by_type,
        "avg_odds":          avg_odds,
        "edge_distribution": [],  # reserved for ML model
    }
    _stats_cache    = result
    _stats_cache_at = now
    logger.info(
        f"Stats cache refreshed — {total} picks, "
        f"{len(by_sport)} sports, {len(by_type)} types"
    )
    return result


@app.delete("/api/picks")
async def clear_picks(_: str = Depends(require_admin)):
    global _stats_cache
    async with SessionLocal() as db:
        await db.execute(delete(Pick))
        await db.commit()
    _stats_cache = None  # invalidate stats cache
    logger.info("All picks cleared by admin")
    return {"ok": True}


class NoteBody(BaseModel):
    user_note: str = ""


@app.patch("/api/picks/{pick_id}/note")
async def update_note(pick_id: int, body: NoteBody, _: str = Depends(require_auth)):
    async with SessionLocal() as db:
        row = (await db.execute(select(Pick).where(Pick.id == pick_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="Pick not found")
        row.user_note = body.user_note or None
        await db.commit()
    return {"ok": True}


class ResultBody(BaseModel):
    result: str  # win | loss | push | void | pending


@app.patch("/api/picks/{pick_id}/result")
async def update_result(pick_id: int, body: ResultBody, _: str = Depends(require_admin)):
    """Grade a pick: set result to win | loss | push | void | pending."""
    valid = {"win", "loss", "push", "void", "pending"}
    if body.result not in valid:
        raise HTTPException(status_code=400, detail=f"result must be one of {valid}")
    global _stats_cache
    async with SessionLocal() as db:
        row = (await db.execute(select(Pick).where(Pick.id == pick_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="Pick not found")
        row.result = body.result
        await db.commit()
        await db.refresh(row)
    _stats_cache = None  # invalidate stats cache
    return {"ok": True, "pick": _row(row)}


class HiddenBody(BaseModel):
    hidden: bool


@app.patch("/api/picks/{pick_id}/hidden")
async def update_hidden(pick_id: int, body: HiddenBody, _: str = Depends(require_admin)):
    """Admin: toggle pick visibility. hidden=true removes it from the public feed."""
    global _stats_cache
    async with SessionLocal() as db:
        row = (await db.execute(select(Pick).where(Pick.id == pick_id))).scalars().first()
        if not row:
            raise HTTPException(status_code=404, detail="Pick not found")
        row.hidden = body.hidden
        await db.commit()
        await db.refresh(row)
    _stats_cache = None
    logger.info(f"Pick {pick_id} ({row.expert}) hidden={body.hidden}")
    return {"ok": True, "pick": _row(row)}


@app.post("/api/grade")
async def grade_now(_: str = Depends(require_admin)):
    """Manually trigger a grading run immediately."""
    if not _SCRAPER_ENABLED:
        raise HTTPException(status_code=503, detail="Scraper not available in API-only mode")
    global _stats_cache
    asyncio.create_task(_run_grade())
    return {"ok": True}

async def _run_grade():
    global _stats_cache
    try:
        result = await run_grader()
        if result.get("graded", 0) > 0:
            _stats_cache = None
        logger.info(f"Manual grade complete: {result}")
    except Exception as e:
        logger.error(f"Manual grade error: {e}")


@app.get("/api/tracker")
async def get_tracker(_: str = Depends(require_auth), expert: str | None = None, sport: str | None = None):
    """
    Per-expert win/loss tracker.
    Returns {experts: [...], overall: {...}}
    Each expert entry: expert, total, wins, losses, pushes, voids, pending,
    graded, win_rate, net_units, roi, streak, streak_type, record, by_sport, recent (last 10).
    """
    import re as _re

    async with SessionLocal() as db:
        q = select(Pick).order_by(Pick.posted_at.asc(), Pick.id.asc())
        if expert:
            q = q.where(Pick.expert == expert)
        if sport:
            q = q.where(Pick.sport == sport)
        rows = (await db.execute(q)).scalars().all()

    def _parse_units(u: str | None) -> float:
        if not u:
            return 1.0
        try:
            cleaned = _re.sub(r"[^\d.]", "", u)
            return float(cleaned) if cleaned else 1.0
        except Exception:
            return 1.0

    by_expert: dict[str, list] = {}
    for p in rows:
        key = p.expert or "Unknown"
        by_expert.setdefault(key, []).append(p)

    def _expert_stats(name: str, picks: list) -> dict:
        wins    = [p for p in picks if p.result == "win"]
        losses  = [p for p in picks if p.result == "loss"]
        pushes  = [p for p in picks if p.result == "push"]
        voids   = [p for p in picks if p.result == "void"]
        pending = [p for p in picks if p.result in (None, "pending")]
        graded  = wins + losses + pushes

        units_won  = sum(_parse_units(p.units) for p in wins)
        units_lost = sum(_parse_units(p.units) for p in losses)
        net_units  = round(units_won - units_lost, 2)
        total_risked = units_won + units_lost
        roi      = round(net_units / total_risked * 100, 1) if total_risked > 0 else 0.0
        win_rate = round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else 0.0

        # Current streak (most recent graded pick first)
        streak = 0
        streak_type: str | None = None
        for p in reversed(graded):
            if p.result == "push":
                continue
            if streak_type is None:
                streak_type = p.result
            if p.result == streak_type:
                streak += 1
            else:
                break

        # Per-sport breakdown
        by_sport: dict[str, dict] = {}
        for p in picks:
            s = p.sport or "Other"
            by_sport.setdefault(s, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0})
            if p.result == "win":
                by_sport[s]["wins"]    += 1
            elif p.result == "loss":
                by_sport[s]["losses"]  += 1
            elif p.result == "push":
                by_sport[s]["pushes"]  += 1
            else:
                by_sport[s]["pending"] += 1

        # Recent 10 picks (most recent first)
        recent = [
            {
                "id":        p.id,
                "pick":      p.pick,
                "game":      p.game,
                "odds":      p.odds,
                "units":     p.units,
                "sport":     p.sport,
                "result":    p.result or "pending",
                "posted_at": p.posted_at,
            }
            for p in list(reversed(picks))[:10]
        ]

        return {
            "expert":      name,
            "total":       len(picks),
            "wins":        len(wins),
            "losses":      len(losses),
            "pushes":      len(pushes),
            "voids":       len(voids),
            "pending":     len(pending),
            "graded":      len(graded),
            "win_rate":    win_rate,
            "net_units":   net_units,
            "roi":         roi,
            "streak":      streak,
            "streak_type": streak_type,
            "record":      f"{len(wins)}-{len(losses)}-{len(pushes)}",
            "by_sport":    by_sport,
            "recent":      recent,
        }

    stats = [_expert_stats(name, p) for name, p in by_expert.items()]
    stats.sort(key=lambda x: (-x["graded"], -x["wins"]))

    all_wins    = sum(s["wins"]    for s in stats)
    all_losses  = sum(s["losses"]  for s in stats)
    all_pushes  = sum(s["pushes"]  for s in stats)
    all_pending = sum(s["pending"] for s in stats)
    all_graded  = all_wins + all_losses + all_pushes
    overall_wr  = round(all_wins / (all_wins + all_losses) * 100, 1) if (all_wins or all_losses) else 0.0

    return {
        "experts": stats,
        "overall": {
            "total":    len(rows),
            "wins":     all_wins,
            "losses":   all_losses,
            "pushes":   all_pushes,
            "pending":  all_pending,
            "graded":   all_graded,
            "win_rate": overall_wr,
        },
    }


# ── T3: Scrape ────────────────────────────────────────────────────────────────

_scraping: bool = False
_scrape_started_at: float | None = None
_SCRAPE_TIMEOUT = 600  # 10 minutes; stale lock auto-released after this


async def _run_with_retry(fn, name: str, retries: int = 3):
    """
    T3: Exponential-backoff retry wrapper for scraper coroutines.
    Waits 5 s, 10 s, 15 s between attempts.
    Returns [] on total failure; never propagates so the other scraper still runs.
    Only retries on transient/unexpected exceptions — auth failures propagate immediately
    only if the scraper itself chooses to raise (current scrapers return [] on auth miss).
    """
    for attempt in range(retries):
        try:
            return await fn()
        except Exception as e:
            if attempt == retries - 1:
                logger.error(f"[T3] {name} scraper failed after {retries} attempts: {e}")
                return []
            delay = 5.0 * (attempt + 1)
            logger.warning(
                f"[T3] {name} attempt {attempt + 1}/{retries} failed: {e} "
                f"— retrying in {delay:.0f}s"
            )
            await asyncio.sleep(delay)
    return []


@app.post("/api/admin/reload")
async def force_reload(_: str = Depends(require_admin)):
    """Broadcast scrape_done to all WS clients, forcing the UI to re-fetch picks."""
    await broadcast({"type": "scrape_done", "source": "reload"})
    return {"ok": True}


@app.post("/api/scrape")
async def scrape_now(source: str = "all", _: str = Depends(require_admin)):
    if not _SCRAPER_ENABLED:
        raise HTTPException(status_code=503, detail="Scraper not available in API-only mode")
    global _scraping, _scrape_started_at
    if _scraping:
        if _scrape_started_at and time.monotonic() - _scrape_started_at > _SCRAPE_TIMEOUT:
            logger.warning("Stale scrape lock detected — releasing automatically")
            _scraping = False
        else:
            return {"ok": False, "message": "Scrape already running"}

    _scraping = True
    _scrape_started_at = time.monotonic()
    asyncio.create_task(_do_scrape(source))
    return {"ok": True}


async def _save_pick(pick: dict):
    """
    Save one pick dict to DB (skip duplicates) and enqueue for WS batch delivery.
    T1: instead of calling broadcast() directly, appends to _pick_batch_queue.
        _flush_batch_loop() will deliver the batch every 2 s.
    """
    global _pick_batch_queue
    source = pick.get("source", "winible")
    async with SessionLocal() as db:
        # Winible: dedup on case-insensitive expert + pick + odds within last 3 days.
        # This handles: (1) expert name casing variants ("CBlez" vs "CBLez"),
        # (2) re-scrapes that shift the date by 1 day (yesterday's cards appearing as today).
        # AN: dedup on expert+pick+posted_at (text is stable, date is reliable)
        if source == "winible":
            cutoff = (datetime.now(_EST).date() - timedelta(days=3)).isoformat()
            existing = (await db.execute(
                select(Pick).where(
                    Pick.source    == source,
                    func.lower(Pick.expert) == (pick.get("expert") or "").lower(),
                    Pick.pick      == pick.get("pick", ""),
                    Pick.odds      == pick.get("odds"),
                    Pick.posted_at >= cutoff,
                )
            )).scalars().first()
        else:
            existing = (await db.execute(
                select(Pick).where(
                    Pick.source    == source,
                    Pick.expert    == pick.get("expert"),
                    Pick.pick      == pick.get("pick", ""),
                    Pick.posted_at == pick.get("posted_at"),
                )
            )).scalars().first()

        if existing:
            return

        pick_text = pick.get("pick", "")
        prop_fields = parse_player_prop(pick_text) if pick.get("pick_type") == "props" else {}
        row = Pick(
            source=source,
            expert=pick.get("expert"),
            record=pick.get("record"),
            pick=pick_text,
            game=pick.get("game"),
            odds=pick.get("odds"),
            sport=pick.get("sport"),
            units=pick.get("units"),
            comment=pick.get("comment"),
            pick_type=pick.get("pick_type"),
            session_id=pick.get("session_id"),
            posted_at=pick.get("posted_at"),
            bet_scope=pick.get("bet_scope") or detect_bet_scope(pick_text),
            player_name=pick.get("player_name") or prop_fields.get("player_name"),
            stat_type=pick.get("stat_type")     or prop_fields.get("stat_type"),
            stat_line=pick.get("stat_line")      or prop_fields.get("stat_line"),
            over_under=pick.get("over_under")    or prop_fields.get("over_under"),
            result=pick.get("result", "pending"),
            # edge_score intentionally left None — reserved for future ML model
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    # T1: queue for batch delivery instead of immediate broadcast
    _pick_batch_queue.append({"type": "new_pick", "pick": _row(row)})


# ── Splits ────────────────────────────────────────────────────────────────────

@app.get("/api/splits")
async def get_splits(_: str = Depends(require_auth), date: str | None = None):
    """
    Returns VSiN betting splits from the in-memory cache (refreshed every 5 min).
    Triggers a one-off fetch on cold start if cache is empty.
    """
    by_date = _splits_cache
    if not by_date:
        await _refresh_splits_cache()
        by_date = _splits_cache

    available = sorted(by_date.keys(), reverse=True)

    if date and date in by_date:
        games = by_date[date]
    elif available:
        games = by_date[available[0]]
        date = available[0]
    else:
        games = []

    return {
        "games":           games,
        "date":            date,
        "available_dates": available,
        "refreshed_at":    _splits_refreshed_at,
    }


async def _do_scrape(source: str):
    global _scraping, _scrape_started_at
    start = time.monotonic()
    # scrape_started broadcasts immediately (not queued) so UI spinner appears instantly
    await broadcast({"type": "scrape_started", "source": source})
    logger.info(f"Scrape started [{source}]")

    try:
        async def on_pick(pick):
            if "__type" in pick:
                # otp_required / otp_done — send immediately, not batched
                await broadcast({"type": pick["__type"]})
                return
            await _save_pick(pick)

        # ── Load checkpoints (incremental scraping) ───────────────────────
        since_winible = get_last_scraped("winible") if source in ("all", "winible") else None
        since_an      = get_last_scraped("action_network") if source in ("all", "action_network") else None
        scrape_time   = datetime.utcnow()   # record before scraping so we don't miss concurrent posts

        # T3: run scrapers concurrently; each has its own retry wrapper
        tasks = []
        if source in ("all", "winible"):
            tasks.append(_run_with_retry(
                lambda: scrape_winible(on_pick=on_pick, since=since_winible), "winible"
            ))
        if source in ("all", "action_network"):
            tasks.append(_run_with_retry(
                lambda: scrape_an(on_pick=on_pick, since=since_an), "action_network"
            ))

        await asyncio.gather(*tasks)

        # ── Update checkpoints only after a successful scrape ─────────────
        if source in ("all", "winible"):
            set_last_scraped("winible", scrape_time)
        if source in ("all", "action_network"):
            set_last_scraped("action_network", scrape_time)

        # Flush any remaining queued picks immediately when scrape finishes
        # (don't wait up to 2s for the loop to fire)
        await _flush_batch()

        elapsed = time.monotonic() - start
        logger.info(f"Scrape complete [{source}] in {elapsed:.1f}s")

    finally:
        _scraping = False
        _scrape_started_at = None
        # scrape_done broadcasts immediately so the UI spinner stops
        await broadcast({"type": "scrape_done", "source": source})


# ── Guest experts config ───────────────────────────────────────────────────────

@app.get("/api/config/guest-experts")
async def get_guest_experts(_: str = Depends(require_auth)):
    """Return the admin-configured list of experts visible to guests."""
    import json as _json
    async with SessionLocal() as db:
        row = (await db.execute(
            select(AppConfig).where(AppConfig.key == "guest_experts")
        )).scalars().first()
    if not row or not row.value:
        return {"experts": []}
    return {"experts": _json.loads(row.value)}


class GuestExpertsBody(BaseModel):
    experts: list[str]

@app.put("/api/config/guest-experts")
async def set_guest_experts(body: GuestExpertsBody, _: str = Depends(require_admin)):
    """Admin-only: set which experts are visible to guests."""
    import json as _json
    async with SessionLocal() as db:
        row = (await db.execute(
            select(AppConfig).where(AppConfig.key == "guest_experts")
        )).scalars().first()
        if row:
            row.value = _json.dumps(body.experts)
        else:
            db.add(AppConfig(key="guest_experts", value=_json.dumps(body.experts)))
        await db.commit()
    return {"ok": True, "experts": body.experts}
