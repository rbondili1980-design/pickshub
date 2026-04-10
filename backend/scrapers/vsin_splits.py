"""
VSiN Betting Splits scraper
Fetches https://data.vsin.com/betting-splits/?source=CIRCA
Returns list of paired game dicts with split percentages.
"""
import re
import asyncio
import httpx
from datetime import date
from bs4 import BeautifulSoup

SPLITS_BASE = "https://data.vsin.com/betting-splits/?source=CIRCA"

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_date_from_header(text: str) -> str | None:
    """'NBA - Monday, Mar 30' → '2026-03-30'"""
    m = re.search(r'(\w{3})\s+(\d{1,2})', text)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1))
    if not month:
        return None
    today = date.today()
    year = today.year
    candidate = date(year, month, int(m.group(2)))
    # If more than 180 days in past, assume next year
    if (candidate - today).days < -180:
        candidate = date(year + 1, month, int(m.group(2)))
    return candidate.isoformat()


def _sport_from_header(text: str) -> str | None:
    """'NBA - Monday, Mar 30' → 'NBA'"""
    m = re.match(r'^([A-Z]{2,4})\s*[-–]', text.strip())
    return m.group(1) if m else None


def _clean_pct(val: str) -> str | None:
    """Strip trend arrows (▲▼), whitespace; return 'XX%' or None."""
    val = re.sub(r'[▲▼\s]', '', val)
    if not val or val in ('-', '—', 'N/A'):
        return None
    if re.match(r'^\d+%$', val):
        return val
    if re.match(r'^\d+$', val):
        return val + '%'
    return None


def _parse_table(table) -> list[dict]:
    """
    Table structure (11 cols per data row):
    [0] action  [1] team  [2] spread_line  [3] spread_handle%  [4] spread_bets%
    [5] total_line  [6] total_handle%  [7] total_bets%
    [8] ml  [9] ml_handle%  [10] ml_bets%
    Header row has 10 cols (no action col, starts with date+sport text).
    """
    rows = table.find_all('tr')
    if not rows:
        return []

    # First row is the header: contains date+sport and column labels
    header_cells = rows[0].find_all(['td', 'th'])
    if not header_cells:
        return []

    header_text = header_cells[0].get_text(' ', strip=True)
    current_date  = _parse_date_from_header(header_text)
    current_sport = _sport_from_header(header_text)

    games = []
    for row in rows[1:]:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 9:
            continue

        texts = [c.get_text(' ', strip=True) for c in cells]

        # Action cell: ↺ = sharp/consensus indicator; a number = game number
        action_text = texts[0].strip()
        is_sharp = '↺' in action_text or '↻' in action_text

        team       = texts[1].strip() if len(texts) > 1 else ''
        spread_line = texts[2].strip() if len(texts) > 2 else None
        # Strip trailing '%' if accidentally attached (shouldn't happen)
        if spread_line and spread_line.endswith('%'):
            spread_line = None

        spread_handle = _clean_pct(texts[3]) if len(texts) > 3 else None
        spread_bets   = _clean_pct(texts[4]) if len(texts) > 4 else None
        total_line    = texts[5].strip() if len(texts) > 5 else None
        total_handle  = _clean_pct(texts[6]) if len(texts) > 6 else None
        total_bets    = _clean_pct(texts[7]) if len(texts) > 7 else None
        ml_raw        = texts[8].strip() if len(texts) > 8 else None
        ml_handle_raw = _clean_pct(texts[9]) if len(texts) > 9 else None
        ml_bets_raw   = _clean_pct(texts[10]) if len(texts) > 10 else None

        if not team:
            continue

        # Clean ML: keep only if it looks like American odds (+105, -1,600, -110 etc.)
        # Reject '-', '—', 'EV', 'PK', etc.
        if ml_raw and re.match(r'^[+-]\d[\d,]*$', ml_raw.replace(',', '')):
            # Also discard when both handle and bets are 0% — nobody bet this line,
            # so the data is meaningless (common for -1,600 / -2,100 type extremes).
            no_action = (ml_handle_raw in ('0%', None) and ml_bets_raw in ('0%', None))
            if no_action:
                ml = ml_handle = ml_bets = None
            else:
                ml        = ml_raw
                ml_handle = ml_handle_raw
                ml_bets   = ml_bets_raw
        else:
            # No valid ML line — null out the handle/bets too (they're meaningless)
            ml = ml_handle = ml_bets = None

        games.append({
            "date":          current_date,
            "sport":         current_sport,
            "team":          team,
            "spread_line":   spread_line,
            "spread_handle": spread_handle,
            "spread_bets":   spread_bets,
            "total_line":    total_line if total_line and total_line not in ('-', '—') else None,
            "total_handle":  total_handle,
            "total_bets":    total_bets,
            "ml":            ml,
            "ml_handle":     ml_handle,
            "ml_bets":       ml_bets,
            "is_sharp":      is_sharp,
        })

    return games


def _null_ml(side: dict) -> None:
    """Zero out ML fields on a team dict in-place."""
    side["ml"] = side["ml_handle"] = side["ml_bets"] = None


def _pair_teams(rows: list[dict]) -> list[dict]:
    """Consecutive rows from the same table form a game pair (away, home)."""
    paired = []
    i = 0
    while i < len(rows):
        away = rows[i]
        if i + 1 < len(rows) and rows[i + 1].get('date') == away.get('date') and rows[i + 1].get('sport') == away.get('sport'):
            home = rows[i + 1]

            # If either side has no ML action, null both — the 100%/0% mirror
            # is just an artefact of one side having zero bets.
            if away.get("ml") is None or home.get("ml") is None:
                _null_ml(away)
                _null_ml(home)

            paired.append({
                "date":         away["date"],
                "sport":        away["sport"],
                "matchup":      f"{away['team']} vs {home['team']}",
                "away":         away,
                "home":         home,
                "total_line":   away.get("total_line"),
                "total_handle": away.get("total_handle"),
                "total_bets":   away.get("total_bets"),
            })
            i += 2
        else:
            paired.append({
                "date":         away["date"],
                "sport":        away["sport"],
                "matchup":      away["team"],
                "away":         away,
                "home":         None,
                "total_line":   away.get("total_line"),
                "total_handle": away.get("total_handle"),
                "total_bets":   away.get("total_bets"),
            })
            i += 1
    return paired


async def _fetch_one_view(client: httpx.AsyncClient, view: str) -> list[dict]:
    url = f"{SPLITS_BASE}&view={view}"
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception as e:
        print(f"[Splits] fetch error ({view}): {e}")
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    all_rows = []
    for tbl in soup.find_all("table"):
        all_rows.extend(_parse_table(tbl))
    return _pair_teams(all_rows)


async def fetch_all_splits() -> dict[str, list[dict]]:
    """
    Fetch all three VSiN views concurrently.
    Returns {date_str: [games]} mapping based on the actual dates in each view.
    """
    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        today_games, tomorrow_games, yesterday_games = await asyncio.gather(
            _fetch_one_view(client, "today"),
            _fetch_one_view(client, "tomorrow"),
            _fetch_one_view(client, "yesterday"),
        )

    by_date: dict[str, list[dict]] = {}
    for game in today_games + tomorrow_games + yesterday_games:
        d = game.get("date")
        if d:
            by_date.setdefault(d, []).append(game)

    return by_date


async def fetch_splits(view: str = "today") -> list[dict]:
    """Legacy single-view fetch — kept for compatibility."""
    if view not in ("today", "tomorrow", "yesterday"):
        view = "today"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as client:
        return await _fetch_one_view(client, view)
