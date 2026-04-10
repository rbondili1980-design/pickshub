"""
Action Network scraper
- Logs in with email/password
- Scrapes /picks (followed experts' picks)
- Parses page text to extract structured picks
"""
import asyncio
import logging
import re
import json
import base64
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from .pick_utils import classify_pick_type, sport_from_pick_text, sport_from_game_abbrevs

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger("sharpslips.action_network")

SOURCE       = "action_network"
URL          = "https://www.actionnetwork.com/picks?tab=following"
LOGIN_URL    = "https://www.actionnetwork.com/login"
COOKIES_FILE = Path(__file__).parent.parent / "cookies" / "action_network.json"

# Visible browser popup is disabled — headless only, skip cycle on failure

# Regexes for parsing the page body text
AGO_RE    = re.compile(r'^\d+\s*[mhd]\s*ago$', re.I)
RECORD_RE = re.compile(r'(\d+-\d+(?:-\d+)?)\s*\(([+\-][\d.]+u?)\)', re.I)
BET_RE    = re.compile(r'[+\-]\d{2,4}|\b[ou]\d+\.?\d*|\bML\b|\bATS\b|\bover\b|\bunder\b', re.I)
SPORT_RE  = re.compile(r'\b(MLB|NBA|NFL|NHL|CBB|CFB|NCAAB|NCAAF|MLS|Soccer)\b', re.I)
SPORT_MAP = {'NCAAB': 'CBB', 'NCAAF': 'CFB'}
FINAL_RE   = re.compile(r'^FINAL(?:\s*-\s*\d+)?\s+(\d{1,2})/(\d{1,2})$', re.I)
COMMENT_RE = re.compile(
    r'^(Good to|Took\b|Bet to\b|Poly\b|Boost\b'
    r"|I[\u2019']m\b|I[\u2019']ll\b|I[\u2019']ve\b|I[\u2019']d\b"  # I'm / I'll
    r"|I\s+[a-z]|My\s+[a-z]|We\s+[a-z]|We[\u2019']re\b"           # first-person commentary
    r'|Like\s+the\b|Love\s+the\b|Fading\b|Backing\b'               # opinion phrases
    r'|Projecting\b|Proj\b|Playing\b|Going\s+[a-z]'                 # analysis phrases incl. "Proj closer to"
    r'|This\s+is\b|This\s+game\b|This\s+line\b'                     # "this is..." commentary
    r'|Closer\s+to\b|Projecting\s+this\b|Line\s+(is|closer)\b'      # edge-case phrasing
    r'|Sharp\s|Value\s+(at|here)\b|Edge\s+(at|here)\b'              # sharp/value/edge analysis
    r'|Expecting\b|Anticipating\b|Leaning\b|Targeting\b'            # more analysis verbs
    r'|Model\s+(has|projects|gives|likes)\b|Consensus\b'            # model/consensus commentary
    r')',
    re.I,
)

# Non-following page sections — stop parsing when we hit any of these
_STOP_SENTINELS = frozenset({
    # These appear in the BOTTOM sidebar, not the top nav — safe to stop here.
    'Suggested Experts',
    'Popular Experts',
    # NOTE: "Discover Experts", "All Picks", "Latest Betting Picks" are NAV TABS
    # that appear at position ~33 in the body — do NOT use them as stop sentinels
    # or the entire pick feed gets cut before a single expert is reached.
})


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


def _save_cookies(cookies: list):
    COOKIES_FILE.parent.mkdir(exist_ok=True)
    COOKIES_FILE.write_text(json.dumps(cookies))


def _load_cookies() -> list:
    if COOKIES_FILE.exists():
        return json.loads(COOKIES_FILE.read_text())
    return []


def _ua_from_cookies(cookies: list) -> str:
    """
    Extract the user-agent that was used when AN_SESSION_TOKEN_V1 was minted.
    Action Network bakes the UA into the JWT — if we send a different UA the
    server rejects the session (returns the logged-out public picks page).
    Falls back to _DEFAULT_UA if the cookie is absent or the JWT can't be parsed.
    """
    for ck in cookies:
        if ck.get("name") == "AN_SESSION_TOKEN_V1":
            try:
                payload_b64 = ck["value"].split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                payload = json.loads(base64.b64decode(payload_b64))
                ua = payload.get("agent", "")
                if ua:
                    return ua
            except Exception:
                pass
    return _DEFAULT_UA


def _ago_to_date(ago_str: str) -> str:
    """Convert '5m ago', '2h ago', '1d ago' to YYYY-MM-DD."""
    today = date.today()
    m = re.match(r'^(\d+)\s*([mhd])\s*ago$', ago_str.strip(), re.I)
    if not m:
        return today.isoformat()
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == 'd':
        return (today - timedelta(days=n)).isoformat()
    # minutes or hours → same day
    return today.isoformat()


def _detect_sport(text):
    m = SPORT_RE.search(text)
    if m:
        s = m.group(1).upper()
        return SPORT_MAP.get(s, s)
    return None


def _detect_sport_in_lines(lines: list[str], start: int, end: int) -> str | None:
    """Scan a range of lines for sport keywords."""
    for k in range(max(0, start), min(end, len(lines))):
        s = _detect_sport(lines[k])
        if s:
            return s
    return None


TEAM_RE   = re.compile(r'^[A-Z]{2,4}$')
UNITS_RE  = re.compile(r'^\d+(\.\d+)?u$', re.I)
TIME_RE   = re.compile(r'^\d{1,2}:\d{2}\s*(AM|PM)$', re.I)
HANDLE_RE = re.compile(r'^@\w+')
URL_RE    = re.compile(r'https?://')
NUM_RE    = re.compile(r'^\d+$')


def _is_noise(line: str) -> bool:
    """Lines to skip that are not picks."""
    return bool(
        HANDLE_RE.match(line) or
        URL_RE.search(line) or
        NUM_RE.match(line) or
        TIME_RE.match(line) or
        UNITS_RE.match(line) or
        RECORD_RE.search(line) or
        COMMENT_RE.match(line) or          # "Good to", "Bet to", etc.
        len(line) > 100 or                 # long explanatory text
        line.lower() in ('follow', 'following', 'unfollow', 'pending picks',
                         'suggested experts', 'discover experts', '@')
    )


def _is_comment(line: str) -> bool:
    """Lines that are expert commentary to attach to the previous pick."""
    return bool(
        COMMENT_RE.match(line) or
        (len(line) > 30 and not URL_RE.search(line) and
         not HANDLE_RE.match(line) and not NUM_RE.match(line) and
         not TIME_RE.match(line) and not UNITS_RE.match(line) and
         not TEAM_RE.match(line) and not FINAL_RE.match(line) and
         not AGO_RE.match(line) and not RECORD_RE.search(line))
    )


def _parse_picks(body_text: str) -> list[dict]:
    """
    Parse the AN picks page body text for logged-in users.
    Expert blocks look like:
      Expert Name
      Xm ago  (or Xh ago, Xd ago)
      Last 30d: 32-18 (+12.4u)   ← optional record
      [Follow / Following]        ← optional button
      Pick text -110
      TEAM1   @   TEAM2          ← game (each on its own line)
      0.1u  /  10:10 PM          ← units / time (noise lines)
      @handle / URL               ← attribution (noise)
      [next pick or next expert]
    """
    # Normalize Unicode apostrophes/quotes so regexes using ' match correctly
    body_text = (body_text
                 .replace('\u2019', "'")   # RIGHT SINGLE QUOTATION MARK  '
                 .replace('\u2018', "'")   # LEFT SINGLE QUOTATION MARK   '
                 .replace('\u02BC', "'")   # MODIFIER LETTER APOSTROPHE   ʼ
                 )
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]
    picks = []
    i = 0

    while i < len(lines):
        # Detect expert block: line N followed by "Xm/h/d ago" on line N+1
        if i + 1 < len(lines) and AGO_RE.match(lines[i + 1]):
            expert = lines[i]
            ago_str = lines[i + 1]
            posted_at = _ago_to_date(ago_str)
            record = None
            j = i + 2

            # Scan ahead up to 4 lines for the record string
            for k in range(j, min(j + 4, len(lines))):
                m = RECORD_RE.search(lines[k])
                if m:
                    record = f"{m.group(1)} ({m.group(2)})"
                    break

            # Skip header noise (record, Follow button, etc.) until we hit a pick line
            while j < len(lines):
                line = lines[j]
                # Stop if next expert block starts
                if j + 1 < len(lines) and AGO_RE.match(lines[j + 1]):
                    break
                if line in _STOP_SENTINELS:
                    break
                # A real pick has a bet marker and is not a noise line
                if BET_RE.search(line) and not _is_noise(line) and len(line) < 150:
                    break
                j += 1

            # Collect picks until next expert block or end sentinel
            while j < len(lines):
                line = lines[j]

                if line in _STOP_SENTINELS:
                    i = len(lines)
                    break

                # Next expert block detected
                if j + 1 < len(lines) and AGO_RE.match(lines[j + 1]):
                    i = j
                    break

                # Comment line → attach to previous pick
                if _is_comment(line) and picks:
                    existing = picks[-1].get("comment") or ""
                    picks[-1]["comment"] = (existing + " | " + line).lstrip(" | ") if existing else line
                    j += 1
                    continue

                # Skip other noise lines between picks
                if _is_noise(line):
                    j += 1
                    continue

                # Pick line: has a bet marker and is not a noise line
                if BET_RE.search(line) and len(line) < 150:
                    # Sport: check pick line first, then scan header area and lookahead
                    sport = _detect_sport(line)

                    # Look ahead up to 12 lines for game info, date, and sport
                    game = None
                    units = None
                    game_date = None   # will be set from FINAL or time line
                    lookahead_end = min(j + 13, len(lines))

                    for k in range(j + 1, lookahead_end):
                        lk = lines[k]

                        # Upcoming game: TEAM1 / @ / TEAM2
                        if (game is None and k + 2 < len(lines) and
                                TEAM_RE.match(lk) and
                                lines[k + 1] == '@' and
                                TEAM_RE.match(lines[k + 2])):
                            game = f"{lk} @ {lines[k + 2]}"

                        # Units
                        if UNITS_RE.match(lk):
                            units = lk

                        # Sport keyword in any lookahead line
                        if not sport:
                            sport = _detect_sport(lk)

                        # Completed game date: "FINAL 3/29" or "FINAL - 10 3/29"
                        fm = FINAL_RE.match(lk)
                        if fm:
                            mo, dy = int(fm.group(1)), int(fm.group(2))
                            yr = date.today().year
                            game_date = date(yr, mo, dy).isoformat()
                            break

                        # Upcoming game time: "10:10 PM" → today
                        if TIME_RE.match(lk) and game_date is None:
                            game_date = date.today().isoformat()

                        # Stop lookahead at next expert block
                        if k + 1 < len(lines) and AGO_RE.match(lines[k + 1]):
                            break

                    # If still no sport, scan the expert block header lines
                    if not sport:
                        sport = _detect_sport_in_lines(lines, i + 2, j)
                    # Fallback 1: infer from statistical terms in the pick text
                    if not sport:
                        sport = sport_from_pick_text(line)
                    # Fallback 2: infer from unambiguous team abbreviations in the game
                    if not sport and game:
                        sport = sport_from_game_abbrevs(game)

                    # No game date found → use today (futures/season-long bets)
                    if game_date is None:
                        from datetime import date as _date
                        game_date = _date.today().isoformat()

                    # Extract odds from the pick line and strip them from pick text.
                    # AN often concatenates odds directly: "Over 5.5-175", "BAL -1.5+113"
                    # The trailing odds pattern is: optional space then +/-XXX at end of string.
                    odds_m = re.search(r'([+\-]\d{3,4})$', line.strip())
                    odds = odds_m.group(1) if odds_m else None
                    # Clean pick text: remove trailing odds so pick = "Over 5.5" not "Over 5.5-175"
                    clean_line = re.sub(r'\s*[+\-]\d{3,4}$', '', line.strip()) if odds else line

                    pick_type = classify_pick_type(clean_line)

                    picks.append({
                        "source":    SOURCE,
                        "expert":    expert,
                        "record":    record,
                        "pick":      clean_line,
                        "game":      game,
                        "odds":      odds,
                        "sport":     sport,
                        "units":     units,
                        "comment":   None,
                        "pick_type": pick_type,
                        "posted_at": game_date,
                    })
                j += 1
            else:
                i = len(lines)
                continue
        else:
            i += 1

    return picks


async def run_scrape(on_pick=None, on_status=None, since=None) -> list[dict]:
    """
    Scrape Action Network picks.

    since — only deliver picks posted ON OR AFTER this date (YYYY-MM-DD string or date object).
            Picks older than this are parsed but not passed to on_pick / returned.
            Pass None to return everything.
    """
    email    = os.getenv("ACTION_NETWORK_EMAIL", "")
    password = os.getenv("ACTION_NETWORK_PASSWORD", "")

    def log(msg):
        logger.info(msg)
        if on_status:
            asyncio.ensure_future(on_status(msg))

    picks = []
    logger.info("Starting Action Network scrape")

    async with async_playwright() as p:

        # ── Step 1: Check saved cookies ──────────────────────────────────
        saved = _load_cookies()
        # Use the EXACT user-agent that was used when the JWT was minted.
        # AN bakes the UA into the token — a mismatch causes silent session rejection.
        ua = _ua_from_cookies(saved) if saved else _DEFAULT_UA
        logger.info(f"AN using UA: {ua[:60]}...")
        # Use non-headless with off-screen position — AN blocks headless fingerprints
        _LAUNCH_ARGS = ["--window-position=-2400,-2400", "--window-size=1280,900"]
        browser = await p.chromium.launch(headless=False, args=_LAUNCH_ARGS)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=ua,
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        needs_login = True
        if saved:
            await ctx.add_cookies(saved)
            page = await ctx.new_page()
            try:
                # Go directly to the Following tab — only works if logged in
                await page.goto(URL + "?tab=following", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)
                on_login_page = "login" in page.url
                has_login_form = bool(await page.query_selector('input[type="email"]'))
                # If logged in, Following tab shows personalised picks (not generic public picks)
                # We detect this by checking if the page redirected to login or still has login form
                # Also check if "Discover Experts" (public) vs expert names (logged in following)
                body_text = await page.evaluate("() => document.body.innerText")
                is_public_only = "Discover Experts" in body_text and "Sign In" in body_text
                needs_login = on_login_page or has_login_form or is_public_only
                logger.info(f"AN cookie check: needs_login={needs_login} url={page.url[:60]}")
            except Exception as e:
                logger.warning(f"AN cookie check failed: {e}")
                needs_login = True
        await browser.close()

        # ── Step 2: Login if needed — headless first, visible as fallback ──
        if needs_login:
            logged_in = False

            # Attempt 1: headless login with stored credentials
            if email and password:
                log("AN: session expired — attempting headless login with stored credentials...")
                try:
                    lb = await p.chromium.launch(headless=False, args=_LAUNCH_ARGS)
                    lctx = await lb.new_context(
                        viewport={"width": 1280, "height": 900},
                        user_agent=_DEFAULT_UA,
                        locale="en-US",
                        timezone_id="America/New_York",
                        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                    )
                    lpage = await lctx.new_page()
                    await lpage.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                    await lpage.wait_for_timeout(1500)

                    email_el = await lpage.query_selector('input[type="email"], input[name="email"]')
                    pw_el    = await lpage.query_selector('input[type="password"]')
                    if email_el and pw_el:
                        await email_el.click()
                        await lpage.wait_for_timeout(300)
                        await email_el.fill(email)
                        await lpage.wait_for_timeout(400)
                        await pw_el.click()
                        await lpage.wait_for_timeout(300)
                        await pw_el.fill(password)
                        await lpage.wait_for_timeout(500)
                        await pw_el.press("Enter")
                        await lpage.wait_for_timeout(6000)

                        if "login" not in lpage.url:
                            _save_cookies(await lctx.cookies())
                            logged_in = True
                            log("AN: headless login succeeded — session saved")
                        else:
                            log("AN: headless login redirected back to login page (reCAPTCHA likely)")
                    await lb.close()
                except Exception as e:
                    logger.warning(f"AN headless login error: {e}")
                    try: await lb.close()
                    except Exception: pass

            # Attempt 2: headless failed — skip silently, retry automatically next cycle
            if not logged_in:
                logger.warning(
                    "AN: headless login failed (reCAPTCHA or session expired) — "
                    "skipping AN this cycle, will retry automatically next scrape"
                )
                return []

        # ── Step 3: Scrape the Following feed ────────────────────────────
        browser = await p.chromium.launch(headless=False, args=_LAUNCH_ARGS)
        fresh_cookies = _load_cookies()
        scrape_ua = _ua_from_cookies(fresh_cookies) if fresh_cookies else _DEFAULT_UA
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=scrape_ua,
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await ctx.add_cookies(fresh_cookies)
        page = await ctx.new_page()

        try:
            resp = await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            if resp and resp.status in (429, 503):
                logger.warning(f"AN scrape: rate-limited (HTTP {resp.status}) — backing off this cycle")
                return []
            await page.wait_for_timeout(4000)

            # Bail out if we landed on a CAPTCHA / access-denied page
            page_title = await page.title()
            if any(w in page_title.lower() for w in ("captcha", "access denied", "just a moment", "blocked")):
                logger.warning(f"AN scrape: blocked page detected ('{page_title}') — skipping cycle")
                return []

            # Click "Following" tab to get only followed experts
            following_clicked = False
            for tab_label in ["Following", "My Experts", "Followed"]:
                try:
                    tab = page.get_by_role("tab", name=tab_label)
                    if await tab.count() > 0:
                        await tab.first.click()
                        await page.wait_for_timeout(2000)
                        following_clicked = True
                        log(f"Clicked '{tab_label}' tab")
                        break
                    # Also try links/buttons with that text
                    btn = page.get_by_text(tab_label, exact=True)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(2000)
                        following_clicked = True
                        log(f"Clicked '{tab_label}' button")
                        break
                except Exception:
                    pass
            if not following_clicked:
                log("Could not find Following tab — scraping full page with sentinel cutoff")

            # Extract ONLY the "Following" section of the page.
            # Use JS to cut the full body text at the first non-following sentinel
            # (e.g. "Suggested Experts", "Latest Betting Picks", etc.) so we never
            # parse picks from experts the user does NOT follow.
            stop_phrases = list(_STOP_SENTINELS)
            body = await page.evaluate("""
                (stopPhrases) => {
                    let text = document.body.innerText;
                    let cutAt = text.length;
                    for (const phrase of stopPhrases) {
                        const idx = text.indexOf(phrase);
                        if (idx !== -1 && idx < cutAt) {
                            cutAt = idx;
                        }
                    }
                    return text.slice(0, cutAt);
                }
            """, stop_phrases)
            log(f"Page text length after following-only cut: {len(body)} chars")
            log("Parsing picks from page body...")
            picks = _parse_picks(body)
            log(f"Found {len(picks)} picks from Action Network")

            # Enrich sport from pick detail links in the DOM
            # AN URLs contain the sport slug: /mlb/picks/..., /nba/picks/..., etc.
            try:
                link_sport_map = await page.evaluate("""
                    () => {
                        const sports = ['mlb','nba','nfl','nhl','ncaab','ncaaf','mls','cbb','cfb'];
                        const map = {};
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.href || '';
                            const m = href.match(/\\/([a-z]+)\\/picks\\//i);
                            if (m && sports.includes(m[1].toLowerCase())) {
                                const sport = m[1].toUpperCase();
                                // Use nearby text as a key to correlate with parsed picks
                                const card = a.closest('[class*="pick"], [class*="bet"], article, li, div');
                                const text = card ? card.innerText.trim().slice(0, 80) : '';
                                if (text) map[text] = sport;
                            }
                        });
                        return map;
                    }
                """)
                # Patch picks that lack sport using the DOM map
                SPORT_MAP2 = {'NCAAB': 'CBB', 'NCAAF': 'CFB'}
                for pick in picks:
                    if pick.get("sport"):
                        continue
                    pick_text = pick.get("pick", "")
                    for card_text, dom_sport in link_sport_map.items():
                        if pick_text in card_text:
                            pick["sport"] = SPORT_MAP2.get(dom_sport, dom_sport)
                            break
                logger.info("DOM sport enrichment complete")
            except Exception as e:
                logger.warning(f"DOM sport enrichment skipped: {e}")

            # Save fresh cookies after every successful scrape to keep session alive
            try:
                _save_cookies(await ctx.cookies())
                logger.info("AN: session cookies refreshed after scrape")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Action Network scrape error: {e}", exc_info=True)
        finally:
            await browser.close()

    # ── Checkpoint filter ────────────────────────────────────────────────────
    # Convert since to a comparable date string (YYYY-MM-DD)
    since_date: str | None = None
    if since is not None:
        if hasattr(since, "date"):          # datetime object
            since_date = since.date().isoformat()
        elif hasattr(since, "isoformat"):   # date object
            since_date = since.isoformat()
        else:
            since_date = str(since)[:10]    # already a string

    new_picks = []
    skipped = 0
    for p in picks:
        posted = (p.get("posted_at") or "")[:10]
        if since_date and posted and posted < since_date:
            skipped += 1
        else:
            new_picks.append(p)

    if since_date:
        logger.info(
            f"AN checkpoint ({since_date}): {len(new_picks)} new picks, {skipped} already seen skipped"
        )

    session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    for p in new_picks:
        p["session_id"] = session_id
        p["scraped_at"] = datetime.utcnow().isoformat() + "Z"
        if on_pick:
            await on_pick(p)

    logger.info(f"Action Network scrape complete — {len(new_picks)} new picks delivered")
    return new_picks
