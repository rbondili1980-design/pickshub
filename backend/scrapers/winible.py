"""
Winible scraper — robust DOM-text + Groq text LLM extraction.

Architecture:
  1. Load page, dismiss cookie popup, infinite-scroll until no new cards appear.
  2. Expand every "see more" link so truncated pick lists are fully visible.
  3. For each card, extract DOM inner_text, clean noise, send to Groq text LLM.
  4. Deduplicate extracted picks (LLM sometimes double-extracts from expanded cards).
  5. Retry once after Groq rate-limit reset window; fall back to Vision if needed.
"""
import asyncio
import logging
import re
import base64
import json
import httpx
import os
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.async_api import async_playwright
from .pick_utils import classify_pick_type, is_valid_pick

logger = logging.getLogger("sharpslips.winible")

WINIBLE_URL       = "https://www.winible.com/picks"
LOGIN_URL         = "https://www.winible.com/login"
GROQ_URL          = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TEXT_MODEL   = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
COOKIES_FILE      = Path(__file__).parent.parent / "cookies" / "winible.json"

# ---------------------------------------------------------------------------
# Noise patterns to strip from card DOM text before sending to LLM
# ---------------------------------------------------------------------------
_NOISE_WORDS = {
    'subscribed', 'subscribe', 'follow', 'share',
    'see less', 'see more', 'started', 'ended', 'final',
    'bet365', 'fanduel', 'draftkings', 'caesars', 'betmgm',
    'kalshi', 'fanatics', 'pointsbet', 'hard rock', 'betrivers',
    'bovada', 'mybookie', 'betway', 'unibet', 'pinnacle',
    'get $250', 'get $300', 'get $100', 'get $200', 'get $500',
    'get $50', 'get 2x winnings', 'get $25',
}
_NOISE_RE = re.compile(
    r'^\$\d+$'                    # bare dollar amounts like "$1500"
    r'|^\d+$'                     # bare numbers (like/comment counts)
    r'|^\d[\d,]* subscribers?$'   # subscriber counts
    r'|^started \d+\s+\w+ ago$'   # "Started 2 hours ago"
    r'|^ended \d+\s+\w+ ago$'
    r'|^-$',                      # bare dash (team separator)
    re.I,
)

# ---------------------------------------------------------------------------
# Groq text prompt — explains Winible DOM structure explicitly
# ---------------------------------------------------------------------------
BATCH_SIZE = 5          # cards per Groq call  (4 calls for 20 cards vs 20 before)

TEXT_PROMPT = """\
Below are {n} sports betting pick cards from Winible.com, separated by [CARD N] markers.

IMPORTANT — card structure: Each card can have two formats:
1. MULTI-PICK LIST: A section heading followed by individual pick lines, e.g.:
     cblez
     5 MLB Plays (1u each)
     10:28 am
     Orioles ML -115 (1u)
     Padres -1½ +150 (1u)
     Blue Jays -1½ -135 (1u)
     Over 8.5 -110 (CLE @ LAD) (1u)
   → Extract each pick line separately.
   → The first line of the card is the expert name (e.g. "cblez").
   → If a pick line mentions a team name or abbreviation (e.g. "Orioles ML"),
     use that as the game. If the game is in parentheses like "(CLE @ LAD)",
     use it directly. If a multi-pick block names a specific game in the heading
     (e.g. "Cubs vs Cardinals Game 1"), use that for ALL picks in that block.
   → cblez-style example with 10+ picks:
     cblez
     10 MLB Plays
     04:12 pm
     Yankees -1.5 -105 (1u)
     Red Sox ML +140 (1u)
     Dodgers -1.5 -115 (1u)
     Padres ML +125 (1u)
     Cardinals +1.5 -125 (0.5u)
     Over 8 -110 (NYY @ BOS) (1u)
     Under 7.5 +100 (LAD @ SD) (1u)
     Braves ML -130 (1u)
     Mets -1.5 -120 (1u)
     Cubs ML +105 (1u)
   → Extract ALL 10 picks — do not stop early.

2. SINGLE PICK EXPANDED: A pick title line, then an expanded betting slip with
   team abbreviations on separate lines, e.g.:
     MLB (.5u)
     04:32 pm
     Guardians ML +225 (.5u)    ← THE PICK (extract this)
     Started 2 hours ago
     Guardians ML               ← same pick repeated — DO NOT extract again
     LAD                        ← away team abbreviation
     CLE                        ← home team abbreviation (game = "LAD @ CLE")
     +225                       ← odds (same as above)
     0.5U
     bet365  +240               ← sportsbook alternative lines — IGNORE THESE
   → Extract ONLY ONE pick per such block: use the first summary pick line.
   → The two team abbreviation lines (e.g., LAD / CLE) tell you the game.

Also ignore: subscriber counts, bookmaker names, dollar promotions, status
timestamps ("Started 2 hours ago"), share counts, and motivational posts.

For each pick return a JSON object:
  expert    — handicapper name (first non-noise line in the card, e.g. "cblez")
  posted_at — YYYY-MM-DD: the date the expert POSTED this pick (NOT the game date).
                          Parse the timestamp shown on the card: "Mar 31", "10:28 am"
                          or "04:32 pm" = today, "2h ago" / "1d ago" = relative to today.
                          NEVER use a future game date (e.g. NBA Finals in June) as posted_at.
  game      — "AWAY @ HOME" using the team abbreviation lines if available,
               or extract from pick text (e.g. "Guardians/Dodgers Under 8" →
               "CLE @ LAD"; "Pirates/Reds U 9" → "PIT @ CIN"; "Nationals ML" →
               "WAS"); null ONLY if truly no teams mentioned anywhere.
               IMPORTANT: For Over/Under total picks, ALWAYS try to extract the
               game from the pick text teams (e.g. "Guardians/Dodgers Under 8"
               → game = "CLE @ LAD"). Do NOT leave game as null if team names
               appear in the pick text.
  pick      — clean bet text: e.g. "Orioles ML", "Padres -1.5", "Over 7",
              "Guardians ML", "Vancouver Canucks +1.5 Puck Line",
              "Guardians/Dodgers Under 8". Keep team names in total picks.
              Do NOT include odds or units in the pick field.
  pick_type — "moneyline" / "spread" / "total" / "props" / "parlay"
              Use "total" for Over/Under game totals. Use "props" for player
              prop bets (e.g. "R.Feltner u3.5 Ks"). Use "parlay" for multi-leg
              parlays. Use "spread" for point spread picks.
  odds      — American odds only, e.g. "-115", "+225"; null if absent
  sport     — MLB / NBA / NHL / NFL / CBB; infer from context or team names
  units     — e.g. "1u", "5u", "0.5u"; null if absent

If a card is a motivational/recap post with no actual bet lines, contribute nothing for that card.
Return a SINGLE flat JSON array containing ALL picks from ALL cards combined — no prose, no markdown fences.
"""

VISION_PROMPT = (
    "Extract every individual bet from this Winible.com pick card screenshot. "
    "For each bet return JSON: expert, posted_at (YYYY-MM-DD), game (AWAY @ HOME or null), "
    "pick (bet text without odds), odds (American format or null), "
    "sport (MLB/NBA/NHL/NFL/CBB or null), units (e.g. '1u' or null). "
    "Return ONLY a JSON array."
)

# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------
_MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
}

_EST = ZoneInfo("America/New_York")

def _normalize_posted_at(raw: str | None) -> str:
    today = datetime.now(_EST).date()

    def _clamp(d: date) -> str:
        """Reject future dates (LLM confusing game date with post date).
        Allow at most tomorrow to handle late-night scrapes near midnight."""
        if d > today + timedelta(days=1):
            return today.isoformat()
        return d.isoformat()

    if not raw:
        return today.isoformat()
    raw = raw.strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', raw)
    if m:
        yr, mo, dy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if abs(yr - today.year) > 1:
            yr = today.year
        try:
            return _clamp(date(yr, mo, dy))
        except ValueError:
            return today.isoformat()
    m = re.match(r'^([A-Za-z]+)\s+(\d{1,2})(?:,?\s*(\d{4}))?$', raw)
    if m:
        mon_str = m.group(1).lower()[:3]
        mo = _MONTH_MAP.get(mon_str)
        dy = int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else today.year
        if abs(yr - today.year) > 1:
            yr = today.year
        if mo:
            try:
                return _clamp(date(yr, mo, dy))
            except ValueError:
                pass
    if raw.lower() in ('today', 'now'):
        return today.isoformat()
    m = re.match(r'^(\d+)\s*([mhd])\s*ago$', raw, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit == 'd':
            return (today - timedelta(days=n)).isoformat()
        return today.isoformat()
    return today.isoformat()


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------
def _save_cookies(cookies: list):
    COOKIES_FILE.parent.mkdir(exist_ok=True)
    COOKIES_FILE.write_text(json.dumps(cookies))

def _load_cookies() -> list:
    if COOKIES_FILE.exists():
        return json.loads(COOKIES_FILE.read_text())
    return []


# ---------------------------------------------------------------------------
# DOM text cleaning
# ---------------------------------------------------------------------------
_SUB_RE = re.compile(r'^\d[\d,]* Subscribers?$', re.I)

def _expert_from_header(text: str) -> str | None:
    for line in [l.strip() for l in text.split('\n') if l.strip()]:
        if not _SUB_RE.match(line) and line.lower() not in ('subscribed', 'subscribe', 'follow'):
            return line
    return None

def _clean_card_text(raw: str) -> str:
    """Strip noise lines from card inner_text before sending to LLM."""
    lines = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if _NOISE_RE.match(s):
            continue
        if s.lower() in _NOISE_WORDS:
            continue
        lines.append(s)
    return '\n'.join(lines)


# Patterns that appear on Winible cards to indicate when a pick was posted.
# We parse these in Phase 1 (DOM only) to decide if the card is new since last scrape.
_TS_NOW_RE   = re.compile(r'^(?:just\s+)?now$', re.I)
_TS_MINS_RE  = re.compile(r'^(\d+)\s*m(?:in(?:utes?)?)?\s+ago$', re.I)
_TS_HOURS_RE = re.compile(r'^(\d+)\s*h(?:ours?)?\s+ago$', re.I)
_TS_DAYS_RE  = re.compile(r'^(\d+)\s*d(?:ays?)?\s+ago$', re.I)
_TS_TIME_RE  = re.compile(r'^(\d{1,2}):(\d{2})\s*(am|pm)$', re.I)
_TS_DATE_RE  = re.compile(r'^([A-Za-z]{3,9})\s+(\d{1,2})(?:,?\s*(\d{4}))?$')

def _parse_card_posted_at(raw_text: str) -> datetime | None:
    """
    Scan raw card inner_text for the first recognisable timestamp line and
    return an aware UTC datetime.  Returns None if no timestamp found OR if
    the timestamp is date-only for today (time unknown — must not skip).

    TWO-PASS strategy:
    - Pass 1: look for DATE-bearing patterns first (relative days, absolute dates).
      These definitively tell us WHICH DAY the card is from.
    - Pass 2: fall back to time-only patterns (always treated as "today").
    This prevents a time-only line ("10:28 am") appearing before an absolute
    date ("Apr 8") from causing yesterday's cards to be misidentified as today.

    Rules:
    - Relative ("2h ago", "30m ago", "1d ago") → exact datetime
    - Date-only ("Apr 9") for TODAY → return None (time unknown, never skip)
    - Date-only for a PAST date → return that date at midnight (safe to skip)
    - Time-only ("10:28 am") → today at that time (yesterday if in future)
    """
    now = datetime.now(_EST)
    month_map = {
        'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
        'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
    }

    # ── Pass 1: date-bearing patterns (definitive day info) ──────────────────
    for line in raw_text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if _TS_NOW_RE.match(s):
            return now                        # just posted — always today
        m = _TS_MINS_RE.match(s)
        if m:
            return now - timedelta(minutes=int(m.group(1)))
        m = _TS_HOURS_RE.match(s)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        m = _TS_DAYS_RE.match(s)
        if m:
            return now - timedelta(days=int(m.group(1)))
        m = _TS_DATE_RE.match(s)
        if m:
            mon = month_map.get(m.group(1).lower()[:3])
            if mon:
                yr = int(m.group(3)) if m.group(3) else now.year
                try:
                    card_date = datetime(yr, mon, int(m.group(2)), tzinfo=_EST)
                    # Date-only + today → time unknown → return None so card is never skipped
                    if card_date.date() >= now.date():
                        return None
                    return card_date
                except ValueError:
                    pass

    # ── Pass 2: time-only fallback (no absolute date found — assume today) ───
    for line in raw_text.split('\n'):
        s = line.strip()
        if not s:
            continue
        m = _TS_TIME_RE.match(s)
        if m:
            h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
            if ampm == 'pm' and h != 12:
                h += 12
            elif ampm == 'am' and h == 12:
                h = 0
            local = now.replace(hour=h, minute=mn, second=0, microsecond=0)
            if local > now:
                local -= timedelta(days=1)
            return local

    return None


# ---------------------------------------------------------------------------
# Groq helpers
# ---------------------------------------------------------------------------
def _parse_groq_response(raw: str) -> list[dict]:
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.M)
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return []

_MAX_RATE_LIMIT_WAIT = 90.0   # never block a scrape longer than this per card

def _parse_reset_seconds(msg: str) -> float:
    m = re.search(r'try again in\s+([\d.]+)s', msg, re.I)
    if m:
        return min(float(m.group(1)) + 2.0, _MAX_RATE_LIMIT_WAIT)
    m = re.search(r'try again in\s+(\d+)m', msg, re.I)
    if m:
        return min(float(m.group(1)) * 60 + 5.0, _MAX_RATE_LIMIT_WAIT)
    return 65.0

async def _groq_text_batch(card_texts: list[str], api_key: str, retries: int = 2) -> tuple[list[dict], bool]:
    """Call text LLM with a batch of cards. Returns (picks, permanently_failed)."""
    n = len(card_texts)
    cards_block = "\n\n".join(f"[CARD {i+1}]\n{t}" for i, t in enumerate(card_texts))
    prompt = TEXT_PROMPT.replace("{n}", str(n)) + "\n\n" + cards_block
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": GROQ_TEXT_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1500,
                        "temperature": 0,
                    },
                )
                if resp.status_code == 429:
                    msg = resp.json().get("error", {}).get("message", "")
                    wait = _parse_reset_seconds(msg)
                    logger.warning(f"Groq text rate limit (attempt {attempt+1}/{retries}), waiting {wait:.0f}s")
                    if attempt < retries - 1:
                        await asyncio.sleep(wait)
                        continue
                    return [], True
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                return _parse_groq_response(raw), False
        except Exception as e:
            logger.error(f"Groq text batch error: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(5)
    return [], True

async def _groq_vision(image_png: bytes, api_key: str, retries: int = 2) -> tuple[list[dict], bool]:
    """Call vision LLM. Returns (picks, permanently_failed)."""
    b64 = base64.b64encode(image_png).decode()
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": GROQ_VISION_MODEL,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ]}],
                        "max_tokens": 1500,
                        "temperature": 0,
                    },
                )
                if resp.status_code == 429:
                    msg = resp.json().get("error", {}).get("message", "")
                    wait = _parse_reset_seconds(msg)
                    logger.warning(f"Groq vision rate limit (attempt {attempt+1}/{retries}), waiting {wait:.0f}s")
                    if attempt < retries - 1:
                        await asyncio.sleep(wait)
                        continue
                    return [], True
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                return _parse_groq_response(raw), False
        except Exception as e:
            logger.error(f"Groq vision error: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(5)
    return [], True


# ---------------------------------------------------------------------------
# Within-card deduplication
# ---------------------------------------------------------------------------
def _dedup_picks(picks: list[dict]) -> list[dict]:
    """Remove duplicate picks extracted from the same card (same pick text + odds)."""
    seen = set()
    result = []
    for p in picks:
        key = (
            (p.get("pick") or "").strip().lower(),
            (p.get("odds") or ""),
            (p.get("posted_at") or ""),
        )
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------
async def _is_logged_in(page) -> bool:
    await page.wait_for_timeout(2000)
    url = page.url
    return "login" not in url and url.rstrip("/") != "https://www.winible.com"

async def _dismiss_popup(page):
    """Click any cookie/privacy consent popup button."""
    for btn_text in ("Allow All", "Accept All", "Accept", "Allow all cookies",
                     "I Accept", "OK", "Got it", "Agree"):
        try:
            btn = page.get_by_role("button", name=btn_text, exact=False)
            if await btn.count() > 0:
                await btn.first.click()
                logger.info(f"Dismissed consent popup via '{btn_text}'")
                await page.wait_for_timeout(1500)
                return
        except Exception:
            pass

async def _scroll_and_load(page, max_rounds: int = 20) -> int:
    """
    Scroll to the bottom repeatedly until no new cards appear.
    Returns the total number of unique cards loaded.
    max_rounds=20 handles feeds with many experts posting throughout the day —
    experts who posted earlier are pushed further down as newer posts arrive.
    """
    prev_count = 0
    stable_rounds = 0  # consecutive rounds with no new cards
    for _ in range(max_rounds):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        cards = await page.query_selector_all('.chakra-card, [class*="chakra-card css"]')
        curr_count = len(cards)
        if curr_count == prev_count:
            stable_rounds += 1
            if stable_rounds >= 2:  # 2 consecutive unchanged rounds = truly at the end
                break
        else:
            stable_rounds = 0
        prev_count = curr_count
    # Scroll back to top so screenshots are in viewport
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)
    return prev_count

async def _expand_see_more(page, max_passes: int = 5):
    """Click all 'see more' / 'show more' / 'load more' links until none remain."""
    _EXPAND_TEXTS = ["see more", "show more", "load more", "read more", "view more"]
    for _ in range(max_passes):
        clicked = 0
        for label in _EXPAND_TEXTS:
            els = await page.query_selector_all(f'text="{label}"')
            for el in els:
                try:
                    await el.scroll_into_view_if_needed()
                    await el.click()
                    clicked += 1
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
        if clicked == 0:
            break
        await page.wait_for_timeout(500)


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
async def run_scrape(on_pick=None, on_status=None, since=None) -> list[dict]:
    """
    Scrape Winible picks.

    Always processes ALL cards from today (posted_at == today) regardless of
    the checkpoint — Winible experts may update or add picks to existing cards
    throughout the day, so we re-process the full day on every run.

    Cards from BEFORE today are skipped (already in DB from a previous day's scrape).

    The `since` parameter is accepted for interface compatibility but ignored for
    Winible; the day-boundary cutoff is always used instead.
    """
    def log(msg):
        logger.info(msg)
        if on_status:
            asyncio.ensure_future(on_status(msg))

    picks: list[dict] = []
    session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set — Winible extraction will return no picks")

    log("Starting Winible scrape (today's cards only — re-processing full current day)")

    async with async_playwright() as p:

        # ── Step 1: Check saved cookies ──────────────────────────────────
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        saved = _load_cookies()
        needs_login = True
        if saved:
            await ctx.add_cookies(saved)
            page = await ctx.new_page()
            try:
                await page.goto(WINIBLE_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
                needs_login = not await _is_logged_in(page)
            except Exception as e:
                logger.warning(f"Cookie check failed: {e}")
                needs_login = True
        await browser.close()

        # ── Step 2: OTP login if needed ──────────────────────────────────
        if needs_login:
            log("Need login — opening browser for OTP (3 min window)...")
            if on_pick:
                await on_pick({"__type": "otp_required"})
            vis = await p.chromium.launch(headless=False)
            vis_ctx = await vis.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
            vis_page = await vis_ctx.new_page()
            await vis_page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(180)
            _save_cookies(await vis_ctx.cookies())
            await vis.close()
            if on_pick:
                await on_pick({"__type": "otp_done"})

        # ── Step 3: Scrape ───────────────────────────────────────────────
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await ctx.add_cookies(_load_cookies())
        page = await ctx.new_page()

        try:
            await page.goto(WINIBLE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)

            await _dismiss_popup(page)

            # Limit scroll depth based on how recent the last scrape was.
            # If we scraped within 2 hours, today's cards will be near the top — no need
            # to scroll deep. Full depth only needed on first run or after a long gap.
            since_dt = since if since is not None else None
            if since_dt and hasattr(since_dt, 'date'):
                hours_since = (datetime.utcnow() - since_dt.replace(tzinfo=None)).total_seconds() / 3600
            elif since_dt:
                try:
                    from datetime import datetime as _dt
                    since_parsed = _dt.strptime(str(since_dt)[:10], "%Y-%m-%d")
                    hours_since = (datetime.utcnow() - since_parsed).total_seconds() / 3600
                except Exception:
                    hours_since = 999
            else:
                hours_since = 999

            if hours_since < 2:
                max_scroll_rounds = 5    # recent run — cards are at the top
            elif hours_since < 8:
                max_scroll_rounds = 10   # same-day gap
            else:
                max_scroll_rounds = 20   # long gap or first run — full depth

            # Scroll until no more cards load (handles infinite scroll)
            total_cards = await _scroll_and_load(page, max_rounds=max_scroll_rounds)
            log(f"Loaded {total_cards} cards after scrolling (max_rounds={max_scroll_rounds}, gap={hours_since:.1f}h)")

            # Expand all truncated pick lists
            await _expand_see_more(page)

            cards = await page.query_selector_all('.chakra-card, [class*="chakra-card css"]')
            log(f"Processing {len(cards)} cards")

            # ── Phase 1: collect all card texts from DOM (fast, no API) ────────
            # Strategy: process ALL cards from today, skip cards from previous days.
            # This ensures we catch new picks added to existing cards during the day.
            card_data: list[tuple[int, str, str]] = []  # (original_idx, expert, clean_text)
            last_expert: str | None = None
            skipped_old = 0
            today_str = datetime.now(_EST).strftime("%Y-%m-%d")

            for idx, card in enumerate(cards):
                try:
                    try:
                        if not await card.is_visible():
                            continue
                    except Exception:
                        continue

                    header_el = await card.query_selector('[class*="chakra-card__header"]')
                    if header_el:
                        header_text = await header_el.inner_text()
                        expert = _expert_from_header(header_text)
                        if expert:
                            last_expert = expert
                    else:
                        expert = last_expert

                    if not expert:
                        continue

                    raw_text = await card.inner_text()

                    # ── Day boundary: skip cards from before today ───────────
                    card_ts = _parse_card_posted_at(raw_text)
                    if card_ts is not None:
                        card_date = card_ts.strftime("%Y-%m-%d")
                        if card_date < today_str:
                            skipped_old += 1
                            logger.debug(f"Card {idx+1} ({expert}): from {card_date} < today — skip")
                            continue
                    # card_ts is None → timestamp unknown → process it (safe default)

                    clean_text = _clean_card_text(raw_text)
                    if clean_text.strip():
                        card_data.append((idx, expert, clean_text))
                    else:
                        logger.debug(f"Card {idx+1}: empty after cleaning — skip")
                except Exception as e:
                    logger.error(f"Card {idx+1} DOM read error: {e}")

            if skipped_old:
                log(f"Skipped {skipped_old} cards from previous days, {len(card_data)} today's cards to process")

            if not card_data:
                log("No cards for today found — skipping Groq entirely")
                return picks   # ← zero API calls, exit immediately

            log(f"Processing {len(card_data)} today's cards in batches of {BATCH_SIZE}")

            # ── Phase 2: process cards in batches via LLM ───────────────────
            _GAME_SENTINELS = frozenset({
                "null", "none", "undefined", "unknown", "n/a", "na", "tbd", "tba", ""
            })
            today_str = datetime.now(_EST).strftime("%Y-%m-%d")
            consecutive_rl_failures = 0
            _MAX_CONSECUTIVE_RL = 3

            for batch_start in range(0, len(card_data), BATCH_SIZE):
                batch = card_data[batch_start: batch_start + BATCH_SIZE]
                texts  = [t for _, _, t in batch]
                labels = [f"card {i+1} ({exp})" for i, (_, exp, _) in enumerate(batch)]
                log(f"Batch {batch_start//BATCH_SIZE + 1}: {labels}")

                all_extracted: list[dict] = []

                if api_key:
                    picks_found, failed = await _groq_text_batch(texts, api_key)

                    if failed:
                        consecutive_rl_failures += 1
                        logger.warning(f"Batch {batch_start//BATCH_SIZE+1} failed (rl={consecutive_rl_failures})")
                        if consecutive_rl_failures >= _MAX_CONSECUTIVE_RL:
                            logger.warning(
                                f"Groq rate-limited {consecutive_rl_failures}x in a row — "
                                f"aborting Winible scrape early, will resume next scheduled slot"
                            )
                            break
                        # Try vision fallback for each card in failed batch individually
                        for orig_idx, exp, _ in batch:
                            try:
                                card_el = cards[orig_idx]
                                png = await card_el.screenshot(type="png")
                                vp_found, v_failed = await _groq_vision(png, api_key)
                                if v_failed:
                                    logger.error(f"Vision also failed for card {orig_idx+1} — skipping batch")
                                    break
                                all_extracted.extend(vp_found)
                            except Exception as e:
                                logger.warning(f"Vision fallback card {orig_idx+1}: {e}")
                    else:
                        consecutive_rl_failures = 0
                        all_extracted = _dedup_picks(picks_found)

                # Filter + save picks from this batch
                for vp in all_extracted:
                    pick_str = (vp.get("pick") or "").strip()
                    if not pick_str:
                        continue
                    if not is_valid_pick(pick_str):
                        logger.warning("LLM extracted invalid pick (skipped): %r", pick_str)
                        continue

                    raw_game = str(vp.get("game") or "").strip()
                    raw_game = re.sub(
                        r'\s+(?:vs?\.?|@)\s+(undefined|null|unknown)\s*$',
                        '', raw_game, flags=re.I
                    ).strip()
                    game = None if raw_game.lower() in _GAME_SENTINELS else raw_game
                    if game and re.search(r'\s+[@]\s*$', game):
                        game = None

                    # Expert fallback: use the first card in the batch if LLM didn't fill it
                    expert_fallback = batch[0][1] if batch else "unknown"
                    pick = {
                        "source":     "winible",
                        "expert":     vp.get("expert") or expert_fallback,
                        "posted_at":  _normalize_posted_at(vp.get("posted_at") or today_str),
                        "pick":       pick_str,
                        "game":       game,
                        "odds":       vp.get("odds"),
                        "sport":      vp.get("sport"),
                        "units":      vp.get("units"),
                        "pick_type":  classify_pick_type(pick_str),
                        "session_id": session_id,
                        "scraped_at": datetime.utcnow().isoformat() + "Z",
                    }
                    picks.append(pick)
                    if on_pick:
                        await on_pick(pick)

                log(f"Batch {batch_start//BATCH_SIZE+1}: {len(all_extracted)} picks extracted")

                # Pace: one 15s pause between batches (5 cards = ~3000 tok; 4 batches/min = 12K TPM — safe)
                if batch_start + BATCH_SIZE < len(card_data):
                    await asyncio.sleep(15)

        except Exception as e:
            logger.error(f"Winible scrape page error: {e}", exc_info=True)
        finally:
            await browser.close()

    log(f"Winible scrape complete — {len(picks)} picks")
    return picks
