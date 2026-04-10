"""
Auto-grader: fetches final scores from Action Network scoreboard API
and grades ungraded picks (win / loss / push) in the DB.

Works for both Action Network and Winible picks — both use the same
game/pick structure so the same matching and evaluation logic applies.

Grading logic:
  - Moneyline: winning_team_id matches picked team → win, else loss
  - Spread:    (picked team score - opp score) > spread_line → win,
               == line (rare) → push, else loss
  - Total:     combined score > total_line → over wins, < → under wins, == → push
  - Props/parlay: skipped (need player-level stats not in this API)

Called by _auto_grade_loop() in main.py every 30 min (offset 15 min from scrape).
"""
import asyncio
import logging
import re
import httpx
from datetime import date, datetime, timedelta
from sqlalchemy import select, or_

logger = logging.getLogger("sharpslips.auto_grader")

AN_SCOREBOARD = "https://api.actionnetwork.com/web/v2/scoreboard/{sport}?date={date}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.actionnetwork.com/",
}

SPORT_SLUG = {
    "MLB": "mlb", "NBA": "nba", "NHL": "nhl", "NFL": "nfl",
    "CBB": "ncaab", "CFB": "ncaaf", "MLS": "mls",
}

# Comprehensive team alias table: lowercase alias → canonical abbr used in AN API
TEAM_ALIASES: dict[str, str] = {
    # MLB
    "astros": "HOU", "houston": "HOU",
    "rangers": "TEX", "texas": "TEX",
    "orioles": "BAL", "baltimore": "BAL",
    "red sox": "BOS", "boston": "BOS",
    "yankees": "NYY", "new york yankees": "NYY",
    "mets": "NYM", "new york mets": "NYM",
    "rays": "TB", "tampa bay": "TB", "tampa": "TB",
    "blue jays": "TOR", "toronto": "TOR",
    "white sox": "CWS", "chicago white sox": "CWS",
    "cubs": "CHC", "chicago cubs": "CHC",
    "guardians": "CLE", "cleveland": "CLE",
    "tigers": "DET", "detroit": "DET",
    "royals": "KC", "kansas city": "KC",
    "twins": "MIN", "minnesota": "MIN",
    "athletics": "ATH", "oakland": "ATH", "ath": "ATH",
    "angels": "LAA", "los angeles angels": "LAA",
    "mariners": "SEA", "seattle": "SEA",
    "cardinals": "STL", "st louis": "STL", "st. louis": "STL",
    "brewers": "MIL", "milwaukee": "MIL",
    "pirates": "PIT", "pittsburgh": "PIT",
    "reds": "CIN", "cincinnati": "CIN",
    "phillies": "PHI", "philadelphia": "PHI",
    "braves": "ATL", "atlanta": "ATL",
    "marlins": "MIA", "miami": "MIA",
    "nationals": "WAS", "washington": "WAS", "wsh": "WAS",
    "dodgers": "LAD", "los angeles dodgers": "LAD",
    "giants": "SF", "san francisco": "SF",
    "padres": "SD", "san diego": "SD",
    "rockies": "COL", "colorado": "COL",
    "diamondbacks": "ARI", "arizona": "ARI", "d-backs": "ARI",
    # NBA
    "lakers": "LAL", "los angeles lakers": "LAL",
    "clippers": "LAC", "los angeles clippers": "LAC",
    "warriors": "GSW", "golden state": "GSW",
    "suns": "PHX", "phoenix": "PHX",
    "nuggets": "DEN", "denver": "DEN",
    "jazz": "UTA", "utah": "UTA",
    "thunder": "OKC", "oklahoma city": "OKC",
    "trail blazers": "POR", "portland": "POR",
    "kings": "SAC", "sacramento": "SAC",
    "timberwolves": "MIN", "minnesota timberwolves": "MIN",
    "celtics": "BOS", "boston celtics": "BOS",
    "knicks": "NYK", "new york knicks": "NYK",
    "nets": "BKN", "brooklyn": "BKN",
    "76ers": "PHI", "sixers": "PHI",
    "raptors": "TOR", "toronto raptors": "TOR",
    "bulls": "CHI", "chicago bulls": "CHI",
    "cavaliers": "CLE", "cleveland cavaliers": "CLE",
    "pistons": "DET", "detroit pistons": "DET",
    "pacers": "IND", "indiana": "IND",
    "bucks": "MIL", "milwaukee bucks": "MIL",
    "heat": "MIA", "miami heat": "MIA",
    "magic": "ORL", "orlando": "ORL",
    "hawks": "ATL", "atlanta hawks": "ATL",
    "hornets": "CHA", "charlotte": "CHA",
    "wizards": "WAS", "washington wizards": "WAS",
    "spurs": "SAS", "san antonio": "SAS",
    "rockets": "HOU", "houston rockets": "HOU",
    "grizzlies": "MEM", "memphis": "MEM",
    "pelicans": "NOP", "new orleans": "NOP",
    "mavericks": "DAL", "dallas": "DAL",
    # NHL
    "maple leafs": "TOR", "toronto maple leafs": "TOR",
    "bruins": "BOS", "boston bruins": "BOS",
    "rangers": "NYR", "new york rangers": "NYR",
    "islanders": "NYI", "new york islanders": "NYI",
    "devils": "NJD", "new jersey": "NJD",
    "flyers": "PHI", "philadelphia flyers": "PHI",
    "penguins": "PIT", "pittsburgh penguins": "PIT",
    "capitals": "WAS", "washington capitals": "WAS",
    "hurricanes": "CAR", "carolina": "CAR",
    "panthers": "FLA", "florida": "FLA",
    "lightning": "TBL", "tampa bay lightning": "TBL",
    "canadiens": "MTL", "montreal": "MTL",
    "senators": "OTT", "ottawa": "OTT",
    "sabres": "BUF", "buffalo": "BUF",
    "red wings": "DET", "detroit red wings": "DET",
    "blackhawks": "CHI", "chicago blackhawks": "CHI",
    "blues": "STL", "st. louis blues": "STL",
    "predators": "NSH", "nashville": "NSH",
    "jets": "WPG", "winnipeg": "WPG",
    "avalanche": "COL", "colorado avalanche": "COL",
    "wild": "MIN", "minnesota wild": "MIN",
    "stars": "DAL", "dallas stars": "DAL",
    "oilers": "EDM", "edmonton": "EDM",
    "flames": "CGY", "calgary": "CGY",
    "canucks": "VAN", "vancouver": "VAN",
    "ducks": "ANA", "anaheim": "ANA",
    "kings": "LAK", "los angeles kings": "LAK",
    "sharks": "SJS", "san jose": "SJS",
    "golden knights": "VGK", "vegas": "VGK",
    "kraken": "SEA", "seattle kraken": "SEA",
    "coyotes": "ARI", "arizona coyotes": "ARI",
    "blue jackets": "CBJ", "columbus": "CBJ",
    # NCAAB / CBB common abbreviations and nicknames
    "michigan": "MICH", "wolverines": "MICH",
    "connecticut": "CONN", "uconn": "CONN", "u conn": "CONN", "huskies": "CONN",
    "tennessee": "TENN", "volunteers": "TENN", "vols": "TENN",
    "duke": "DUKE", "blue devils": "DUKE",
    "kansas": "KU", "jayhawks": "KU",
    "kentucky": "UK", "wildcats": "UK",
    "houston": "HOU",  # note: disambiguated by sport slug
    "alabama": "ALA", "crimson tide": "ALA",
    "arkansas": "ARK", "razorbacks": "ARK",
    "baylor": "BAY", "bears": "BAY",
    "florida": "FLA", "gators": "FLA",
    "gonzaga": "GONZ", "bulldogs": "GONZ",
    "iowa": "IOWA", "hawkeyes": "IOWA",
    "iowa state": "ISU", "cyclones": "ISU",
    "marquette": "MARQ", "golden eagles": "MARQ",
    "memphis": "MEM",
    "michigan state": "MIST", "spartans": "MIST",
    "north carolina": "UNC", "tar heels": "UNC",
    "purdue": "PUR", "boilermakers": "PUR",
    "st johns": "STJN", "red storm": "STJN",
    "texas": "TEX",
    "villanova": "NOVA", "wildcats nova": "NOVA",
    "xavier": "XAV", "musketeers": "XAV",
    "oklahoma": "OKLA", "sooners": "OKLA",
    "colorado": "COLO", "buffaloes": "COLO",
    "minnesota": "MINN", "golden gophers": "MINN",
    "bay area": "BAY",
}


def _norm(s: str) -> str:
    """Lowercase, strip punctuation for fuzzy matching."""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _resolve_team(token: str, teams_in_game: list[dict]) -> dict | None:
    """
    Given a raw token from a pick (e.g. 'Astros', 'HOU', 'Houston Astros'),
    return the matching team dict from the AN game, or None.
    """
    tok_norm = _norm(token)
    # Direct abbr match
    for t in teams_in_game:
        if t.get("abbr", "").upper() == token.upper():
            return t
    # Alias match
    canonical = TEAM_ALIASES.get(tok_norm)
    if canonical:
        for t in teams_in_game:
            if t.get("abbr", "").upper() == canonical:
                return t
    # Partial name match (e.g. "Dodgers" in "Los Angeles Dodgers")
    for t in teams_in_game:
        full = _norm(t.get("full_name", ""))
        disp = _norm(t.get("display_name", ""))
        short = _norm(t.get("short_name", ""))
        loc = _norm(t.get("location", ""))
        if tok_norm and (
            tok_norm in full or tok_norm in disp or tok_norm in short or tok_norm in loc
            or full.endswith(tok_norm) or disp == tok_norm or short == tok_norm
        ):
            return t
    return None


def _game_teams_match(pick_game: str, an_game: dict) -> bool:
    """
    Returns True if the pick's game string plausibly refers to this AN game.
    pick_game examples: "Astros vs Red Sox", "TEX @ BAL", "Nationals vs Phillies"
    """
    if not pick_game:
        return False
    teams = an_game.get("teams", [])
    team_abbrs = {t["abbr"].upper() for t in teams}
    team_full  = {_norm(t.get("full_name","")) for t in teams}
    team_disp  = {_norm(t.get("display_name","")) for t in teams}
    team_short = {_norm(t.get("short_name","")) for t in teams}
    team_loc   = {_norm(t.get("location","")) for t in teams}

    # Split pick_game by common separators (@ vs / at)
    parts = re.split(r"\s*(?:vs?\.?|@|at|/)\s*", pick_game, flags=re.I)
    if len(parts) < 2:
        # Single token — check if it matches either team
        tok = _norm(pick_game)
        return (
            tok in team_abbrs or
            any(tok in f for f in team_full) or
            any(tok in d for d in team_disp)
        )

    matched = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if (part.upper() in team_abbrs or
            _norm(part) in team_full or
            _norm(part) in team_disp or
            _norm(part) in team_short or
            _norm(part) in team_loc or
            any(_norm(part) in f for f in team_full) or
            any(_norm(part) in d for d in team_disp) or
            TEAM_ALIASES.get(_norm(part), "").upper() in team_abbrs):
            matched += 1

    return matched >= 1  # at least one team identified


def _extract_pick_team(pick_text: str) -> str | None:
    """
    Extract the team name from a pick like:
      "Astros -1.5", "Rays ML", "Athletics ML", "Over 9", "Pirates Under 3.5",
      "ARI -110 (F5)", "TB +110 (F5)"
    Returns the team string or None for pure totals.
    """
    pick_norm = pick_text.strip()
    # Pure totals — no team
    if re.match(r"^(over|under|o|u)\s*\d", pick_norm, re.I):
        return None
    # Remove scope suffixes like (F5), (1H), (2H), (F5), (Regulation)
    pick_norm = re.sub(r'\s*\([^)]+\)\s*$', '', pick_norm).strip()
    # Remove embedded over/under + line from the end: "Pirates Under 3.5" → "Pirates"
    pick_norm = re.sub(r'\s+(over|under|o|u)\s*\d+\.?\d*\b.*$', '', pick_norm, flags=re.I).strip()
    # Remove trailing odds: "-110", "+250", "ML", "ATS"
    team = re.sub(r"\s+([+\-]\d{2,4}|ML|ATS)\s*$", "", pick_norm, flags=re.I).strip()
    # Remove remaining trailing spread/line: "-8", "+3.5", "-14.5" (e.g. "MICH -8" → "MICH")
    team = re.sub(r"\s+[+\-]?\d+\.?\d*\s*$", "", team).strip()
    # Remove leading unit markers like "5u"
    team = re.sub(r"^\d+(\.\d+)?u\s+", "", team, flags=re.I).strip()
    return team if team else None


def _parse_spread(pick_text: str) -> tuple[str | None, float | None]:
    """
    Parse a spread pick like "Astros -1.5" or "TEX +3.5".
    Returns (team_token, line) or (None, None).
    """
    m = re.match(r"^(.+?)\s+([+\-]\d+\.?\d*)$", pick_text.strip())
    if m:
        team = m.group(1).strip()
        line = float(m.group(2))
        # Skip if team looks like just odds (e.g. "+165")
        if re.match(r"^[+\-]\d+$", team):
            return None, None
        return team, line
    return None, None


def _parse_total(pick_text: str) -> tuple[str | None, float | None]:
    """
    Parse "Over 9", "Under 8.5-108", "O9.5", "U8".
    Returns ("over"/"under", line) or (None, None).
    """
    m = re.match(r"^(over|under|o|u)\s*(\d+\.?\d*)", pick_text.strip(), re.I)
    if m:
        direction = "over" if m.group(1).lower() in ("over", "o") else "under"
        return direction, float(m.group(2))
    return None, None


def _grade_pick(pick_row, an_game: dict, matched_via_game_field: bool = False) -> str:
    """
    Evaluate a single pick against a completed AN game.
    Returns "win" | "loss" | "push" | "skip" (can't determine).
    """
    pick_type = (pick_row.pick_type or "").lower()
    pick_text = (pick_row.pick or "").strip()
    teams     = an_game.get("teams", [])
    boxscore  = an_game.get("boxscore", {})
    away_id   = an_game.get("away_team_id")
    home_id   = an_game.get("home_team_id")
    winner_id = an_game.get("winning_team_id")

    away_score = boxscore.get("total_away_points")
    home_score = boxscore.get("total_home_points")

    if away_score is None or home_score is None:
        return "skip"

    away_team = next((t for t in teams if t["id"] == away_id), None)
    home_team = next((t for t in teams if t["id"] == home_id), None)
    if not away_team or not home_team:
        return "skip"

    # ── Totals ──────────────────────────────────────────────────────────────
    direction, total_line = _parse_total(pick_text)
    if direction and total_line is not None:
        combined = away_score + home_score
        if combined > total_line:
            return "win" if direction == "over" else "loss"
        elif combined < total_line:
            return "win" if direction == "under" else "loss"
        else:
            return "push"

    # ── Moneyline ────────────────────────────────────────────────────────────
    if pick_type == "moneyline" or re.search(r"\bML\b", pick_text, re.I):
        team_tok = _extract_pick_team(pick_text)
        # Fallback: if pick text has no usable team (e.g. "ML -153"),
        # and we matched this game via the game field, use the game field as team
        if not team_tok and matched_via_game_field and pick_row.game and pick_row.game != 'None':
            team_tok = pick_row.game
        if not team_tok:
            return "skip"
        picked = _resolve_team(team_tok, teams)
        if not picked:
            return "skip"
        if winner_id is None:
            # Draw / tie
            return "push"
        return "win" if picked["id"] == winner_id else "loss"

    # ── Spread ───────────────────────────────────────────────────────────────
    if pick_type == "spread":
        team_tok, line = _parse_spread(pick_text)
        if team_tok is None or line is None:
            return "skip"
        picked = _resolve_team(team_tok, teams)
        if not picked:
            return "skip"
        # Determine which score belongs to picked team
        if picked["id"] == away_id:
            pick_score, opp_score = away_score, home_score
        else:
            pick_score, opp_score = home_score, away_score
        margin = pick_score - opp_score  # positive = picked team won
        covered = margin + line          # add the line (e.g. -1.5 means need to win by >1.5)
        if covered > 0:
            return "win"
        elif covered < 0:
            return "loss"
        else:
            return "push"

    # ── Generic: try total then spread then ML in order ──────────────────────
    # Many picks don't have pick_type set cleanly
    direction, total_line = _parse_total(pick_text)
    if direction and total_line is not None:
        combined = away_score + home_score
        if combined > total_line:
            return "win" if direction == "over" else "loss"
        elif combined < total_line:
            return "win" if direction == "under" else "loss"
        else:
            return "push"

    team_tok, line = _parse_spread(pick_text)
    if team_tok and line is not None:
        picked = _resolve_team(team_tok, teams)
        if picked:
            if picked["id"] == away_id:
                pick_score, opp_score = away_score, home_score
            else:
                pick_score, opp_score = home_score, away_score
            covered = (pick_score - opp_score) + line
            if covered > 0:   return "win"
            elif covered < 0: return "loss"
            else:             return "push"

    # ML fallback: try extracting team
    team_tok = _extract_pick_team(pick_text)
    if team_tok:
        picked = _resolve_team(team_tok, teams)
        if picked and winner_id is not None:
            return "win" if picked["id"] == winner_id else "loss"

    return "skip"


async def _fetch_games(sport_slug: str, date_str: str) -> list[dict]:
    """Fetch completed games from AN scoreboard API for a given sport+date."""
    url = AN_SCOREBOARD.format(sport=sport_slug, date=date_str.replace("-", ""))
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers=HEADERS)
            r.raise_for_status()
            data = r.json()
            games = data.get("games", [])
            # Only return completed games
            return [g for g in games if g.get("status") in ("complete", "closed")]
    except Exception as e:
        logger.warning(f"Scoreboard fetch failed {sport_slug}/{date_str}: {e}")
        return []


async def run_grader() -> dict:
    """
    Main entry point. Finds all ungraded picks with a real posted_at date,
    fetches scores for each sport+date combination, grades each pick.
    Returns summary dict with counts.
    """
    from models import Pick, SessionLocal
    from sqlalchemy import select, or_

    graded_count = 0
    skipped_count = 0
    error_count = 0

    # Load all ungraded picks that have a real date (not 'futures') and a sport
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Pick).where(
                or_(Pick.result == None, Pick.result == "pending"),
                Pick.posted_at != None,
                Pick.posted_at != "futures",
                Pick.sport != None,
                Pick.pick_type.notin_(["props", "parlay"]),
            )
        )).scalars().all()

    if not rows:
        logger.info("Auto-grader: no ungraded picks to process")
        return {"graded": 0, "skipped": 0, "errors": 0}

    logger.info(f"Auto-grader: {len(rows)} ungraded picks to evaluate")

    # Group by (sport, date) to minimise API calls
    from collections import defaultdict
    by_sport_date: dict[tuple, list] = defaultdict(list)
    for row in rows:
        slug = SPORT_SLUG.get(row.sport.upper() if row.sport else "")
        if not slug:
            skipped_count += 1
            continue
        # Grade picks from up to 14 days ago (wider window catches any near-misses)
        pick_date = row.posted_at
        try:
            pd = date.fromisoformat(pick_date)
            if pd > date.today():
                skipped_count += 1
                continue
            if (date.today() - pd).days > 14:
                skipped_count += 1
                continue
        except Exception:
            skipped_count += 1
            continue
        by_sport_date[(slug, pick_date)].append(row)

    # Fetch scores and grade
    for (sport_slug, pick_date), pick_rows in by_sport_date.items():
        games = await _fetch_games(sport_slug, pick_date)
        if not games:
            logger.debug(f"No completed games found for {sport_slug}/{pick_date}")
            skipped_count += len(pick_rows)
            continue

        async with SessionLocal() as db:
            for pick_row in pick_rows:
                try:
                    # ── Strategy 1: game field has a proper "TEAM @ TEAM" or "TEAM vs TEAM" shape ──
                    matched_game = None
                    matched_via_game_field = False
                    raw_game = pick_row.game if pick_row.game and pick_row.game != 'None' else None
                    game_str = raw_game if (
                        raw_game and
                        re.search(r'[@/]|\bvs?\.?\b', raw_game, re.I)
                    ) else None
                    if game_str:
                        for g in games:
                            if _game_teams_match(game_str, g):
                                matched_game = g
                                break

                    # ── Strategy 2: extract team from pick text, scan all games ──
                    if not matched_game:
                        team_tok = _extract_pick_team(pick_row.pick or '')
                        if team_tok:
                            for g in games:
                                if _resolve_team(team_tok, g.get('teams', [])):
                                    matched_game = g
                                    break

                    # ── Strategy 3: game field is a single team name (e.g. "Marlins", "Guardians") ──
                    if not matched_game and raw_game:
                        for g in games:
                            if _resolve_team(raw_game, g.get('teams', [])):
                                matched_game = g
                                matched_via_game_field = True
                                break

                    if not matched_game:
                        logger.debug(
                            f"No game match for pick {pick_row.id}: "
                            f"'{pick_row.pick}' game='{pick_row.game}'"
                        )
                        skipped_count += 1
                        continue

                    result = _grade_pick(pick_row, matched_game, matched_via_game_field=matched_via_game_field)
                    if result == "skip":
                        skipped_count += 1
                        continue

                    # Write to DB — re-fetch and guard against race with admin manual grades.
                    # If admin already set a non-pending result while we were running, skip.
                    row = (await db.execute(
                        select(Pick).where(Pick.id == pick_row.id)
                    )).scalars().first()
                    if row and row.result in (None, "pending"):
                        row.result = result
                        await db.commit()
                        graded_count += 1
                        logger.info(f"Graded pick {pick_row.id} ({pick_row.expert}): '{pick_row.pick}' → {result}")
                    elif row:
                        logger.info(f"Pick {pick_row.id} already manually graded as '{row.result}' — skipping auto-grade")

                except Exception as e:
                    logger.error(f"Error grading pick {pick_row.id}: {e}")
                    error_count += 1

        # Small delay between sport/date batches to be polite to the API
        await asyncio.sleep(1)

    logger.info(f"Auto-grader complete — graded={graded_count} skipped={skipped_count} errors={error_count}")
    return {"graded": graded_count, "skipped": skipped_count, "errors": error_count}
