"""
Shared utilities for classifying sports betting picks.
"""
import re

# ── Sport inference from pick text ───────────────────────────────────────────
# These patterns are unambiguous sport signals inside the pick string itself.

_MLB_PICK_RE = re.compile(
    r'\b(HR|home\s*run|strikeout|ks?\b|rbi|stolen\s+base|batting|era|whip'
    r'|hits?\b|walks?\b|total\s+bases|outs?\b|inning|inn\b|1st\s+inn|f5\b|nrfi|yrfi'
    r'|hits?\s+allowed|walks?\s+allowed|earned\s+run'
    r'|guardians|yankees|red\s*sox|dodgers|cubs|brewers|padres|cardinals'
    r'|braves|phillies|mets|marlins|nationals|pirates|reds|rockies'
    r'|diamondbacks|giants|astros|rangers|mariners|athletics|angels'
    r'|twins|royals|white\s*sox|tigers|orioles|rays|blue\s*jays|expos)\b',
    re.I,
)
_NHL_PICK_RE = re.compile(
    r'\b(goal|save|shot|gaa|puck|power\s*play|pp\b|anytime\s+goal)\b',
    re.I,
)
_NFL_PICK_RE = re.compile(
    r'\b(rushing|passing|receiving|touchdown|td\b|reception|carry|carries'
    r'|qb\b|wr\b|rb\b|te\b|sack|interception)\b',
    re.I,
)
_NBA_PICK_RE = re.compile(
    r'\b(rebound|rebs?\b|assist|3-?pt|three-?pt|triple.double|double.double'
    r'|steal\b|block\b|pts\b|3s\b|made\s+three|made\s+3)\b',
    re.I,
)

_CBB_GAME_RE = re.compile(
    r'\b(uconn|u\s*conn|conn\b|connecticut|mich\b|michigan|duke\b|kansas\b'
    r'|kentucky|gonzaga|villanova|purdue|baylor|ucla|ncaab|cbb'
    r'|march\s+madness|elite\s+eight|sweet\s+sixteen|final\s+four'
    r'|ncaa\s+tournament|first\s+four|round\s+of\s+64|round\s+of\s+32)\b',
    re.I,
)

# Abbreviations that uniquely identify one sport (not shared with any other
# major North American sport in active use as of 2025-26 season).
# Key = upper-case abbreviation, value = sport string.
_EXCLUSIVE_TEAM_SPORT: dict[str, str] = {
    # MLB only
    "NYY": "MLB", "NYM": "MLB", "LAD": "MLB", "MIL": "MLB",
    "CWS": "MLB", "CHW": "MLB", "TBR": "MLB", "LAA": "MLB",
    "ATH": "MLB", "OAK": "MLB", "KCR": "MLB",
    "TEX": "MLB",   # Texas Rangers (no other active major sport uses TEX)
    "ARI": "MLB",   # Diamondbacks (Coyotes moved to Utah 2024)
    "SD":  "MLB",   # Padres (no NHL/NBA team in San Diego)
    "SDP": "MLB",
    "CHC": "MLB",   # Cubs
    # NHL only
    "VGK": "NHL", "WPG": "NHL", "CBJ": "NHL", "NSH": "NHL",
    "NJD": "NHL", "ANA": "NHL", "SJS": "NHL", "SJ": "NHL",
    "TBL": "NHL",
    # NFL only
    "NE": "NFL", "GB": "NFL", "LV": "NFL", "LAR": "NFL",
    # NBA only
    "LAL": "NBA",   # Lakers
    "GSW": "NBA", "SAS": "NBA", "OKC": "NBA",
    "NOP": "NBA", "BKN": "NBA", "MEM": "NBA", "SAC": "NBA",
    "CHA": "NBA",
}


def sport_from_pick_text(pick: str) -> str | None:
    """
    Infer sport from statistical terms in the pick string.
    Returns 'MLB', 'NHL', 'NFL', 'NBA', 'CBB', or None if not determinable.
    """
    if not pick:
        return None
    if _CBB_GAME_RE.search(pick):
        return "CBB"
    if _MLB_PICK_RE.search(pick):
        return "MLB"
    if _NHL_PICK_RE.search(pick):
        return "NHL"
    if _NFL_PICK_RE.search(pick):
        return "NFL"
    if _NBA_PICK_RE.search(pick):
        return "NBA"
    # Game total in range 7.5–20 is unambiguously MLB — NHL tops out at ~7,
    # NBA/NFL/CFB totals are 35+ and 100+ respectively
    m = re.search(r'\b(?:over|under|[ou])\s*(\d+\.?\d*)\b', pick, re.I)
    if m:
        total = float(m.group(1))
        if 7.5 <= total <= 20:
            return "MLB"
        if total > 100:
            return "NBA"
    return None


def sport_from_game_abbrevs(game: str) -> str | None:
    """
    Infer sport from team abbreviations OR full team names in a game string.
    Returns a sport only when the match is unambiguous.
    """
    if not game:
        return None
    # Check abbreviated tokens first (fast path)
    tokens = re.findall(r'\b[A-Z]{2,4}\b', game.upper())
    for tok in tokens:
        sport = _EXCLUSIVE_TEAM_SPORT.get(tok)
        if sport:
            return sport
    # Fall back to full-name patterns in the game string
    return sport_from_pick_text(game)

# ── Pick type classification ─────────────────────────────────────────────────

# Player prop stat keywords
_PROP_RE = re.compile(
    r'\b(3-?pts?|3s\b|pts?\b|rebs?\b|asts?\b|yds?\b|tds?\b|hrs?\b|rbis?\b'
    r'|strikeouts?|saves?\b|goals?\b|shots?\b|blks?\b|blocks?\b|stls?\b|steals?\b'
    r'|assists?\b|passing|rushing|receiving|double-?double|triple-?double'
    r'|anytime|first\s+td|last\s+td|to\s+score|fantasy|threes?\b|treys?\b'
    r'|hits?\b|bases?\b|walks?\b|inning|ks?\b)\b',
    re.I,
)

# Over / Under totals  — "Over 220", "Under 8.5", "O220.5", "U8.5", "u2.5"
_TOTAL_RE = re.compile(r'\b(over|under)\s+\d|\b[ou]\s*\d+\.?\d*\b', re.I)

# Spread — a 1-2-digit number with sign that is NOT 3-4 digit odds
# e.g. "-3", "+7.5", "-14", but NOT "-110", "+200"
_SPREAD_RE = re.compile(r'(?<!\d)[+-]\d{1,2}(?:\.\d)?\b(?!\d)|\bATS\b', re.I)

# Moneyline explicit label
_ML_RE = re.compile(r'\bML\b|\bmoneyline\b', re.I)

# 3+ digit odds like -110, +200, -115 — presence suggests a wager exists
_ODDS_RE = re.compile(r'[+-]\d{3,4}\b')

# Parlay / same-game parlay
_PARLAY_RE = re.compile(r'\bparlay\b', re.I)

# Half-symbol spreads: "+7½", "-3½" (unicode fraction)
_HALF_SPREAD_RE = re.compile(r'[+-]\d+[½]|\b\d+[½]')


# ── Bet scope detection ──────────────────────────────────────────────────────

_SCOPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # MLB / baseball segments
    (re.compile(r'\b(nrfi|yrfi)\b', re.I),                          'inning_1'),
    (re.compile(r'\b1st\s*inn(?:ing)?\b|inn(?:ing)?\s*1\b', re.I),  'inning_1'),
    (re.compile(r'\bf5\b|first\s+5\s+inn', re.I),                   'f5'),
    # Hockey periods
    (re.compile(r'\b1st\s*per(?:iod)?\b|per(?:iod)?\s*1\b', re.I),  'period_1'),
    (re.compile(r'\b2nd\s*per(?:iod)?\b|per(?:iod)?\s*2\b', re.I),  'period_2'),
    (re.compile(r'\b3rd\s*per(?:iod)?\b|per(?:iod)?\s*3\b', re.I),  'period_3'),
    (re.compile(r'\bregulation\b', re.I),                            'regulation'),
    # Basketball / football halves
    (re.compile(r'\b1st\s*half\b|half\s*1\b|fh\b', re.I),           'half_1'),
    (re.compile(r'\b2nd\s*half\b|half\s*2\b|sh\b', re.I),           'half_2'),
    # Quarters
    (re.compile(r'\b1st\s*q(?:uarter)?\b|q1\b', re.I),              'q1'),
    (re.compile(r'\b2nd\s*q(?:uarter)?\b|q2\b', re.I),              'q2'),
    (re.compile(r'\b3rd\s*q(?:uarter)?\b|q3\b', re.I),              'q3'),
    (re.compile(r'\b4th\s*q(?:uarter)?\b|q4\b', re.I),              'q4'),
    # Live
    (re.compile(r'\blive\b', re.I),                                  'live'),
]


def detect_bet_scope(pick: str) -> str | None:
    """
    Detect the game segment a bet covers.
    Returns one of: inning_1 | f5 | half_1 | half_2 | q1-q4 |
                    period_1-period_3 | regulation | live | full_game | None.
    Returns 'full_game' when no segment qualifier is found and the pick
    has enough content to classify (avoids returning full_game for empty/None).
    """
    if not pick:
        return None
    for pattern, scope in _SCOPE_PATTERNS:
        if pattern.search(pick):
            return scope
    return 'full_game'


# ── Player prop parsing ───────────────────────────────────────────────────────

# Maps raw stat keywords found in pick text → canonical stat_type codes
_STAT_ALIASES: dict[str, str] = {
    # Basketball
    'pts': 'PTS', 'points': 'PTS',
    'reb': 'REB', 'rebs': 'REB', 'rebound': 'REB', 'rebounds': 'REB',
    'ast': 'AST', 'asts': 'AST', 'assist': 'AST', 'assists': 'AST',
    'blk': 'BLK', 'blks': 'BLK', 'block': 'BLK', 'blocks': 'BLK',
    'stl': 'STL', 'stls': 'STL', 'steal': 'STL', 'steals': 'STL',
    '3pt': '3PM', '3pts': '3PM', 'three': '3PM', 'threes': '3PM',
    'trey': '3PM', 'treys': '3PM', '3s': '3PM',
    'double-double': 'DD', 'doubledouble': 'DD',
    'triple-double': 'TD2', 'tripledouble': 'TD2',
    # Baseball
    'hr': 'HR', 'home run': 'HR', 'home runs': 'HR',
    'k': 'K', 'ks': 'K', 'strikeout': 'K', 'strikeouts': 'K',
    'rbi': 'RBI', 'rbis': 'RBI',
    'hit': 'H', 'hits': 'H',
    'walk': 'BB', 'walks': 'BB',
    'total bases': 'TB', 'bases': 'TB',
    # Football
    'passing yds': 'PASS_YDS', 'passing yards': 'PASS_YDS',
    'rushing yds': 'RUSH_YDS', 'rushing yards': 'RUSH_YDS',
    'receiving yds': 'REC_YDS', 'receiving yards': 'REC_YDS',
    'yds': 'YDS', 'yards': 'YDS',
    'td': 'TD', 'tds': 'TD', 'touchdown': 'TD', 'touchdowns': 'TD',
    'reception': 'REC', 'receptions': 'REC',
    # Hockey
    'goal': 'G', 'goals': 'G',
    'save': 'SV', 'saves': 'SV',
    'shot': 'SOG', 'shots': 'SOG',
    'point': 'PTS', 'points': 'PTS',
}

# Match: "Player Name o/over/u/under <line>" or "<line> o/u" patterns
# Group 1 = player name (optional), Group 2 = over|under|o|u, Group 3 = line
_PROP_PLAYER_RE = re.compile(
    r'([A-Z][a-z]+(?:\s+[A-Z]\.?\s*[A-Za-z]+)+)\s+'  # "First Last" or "F. Last"
    r'(?:(over|under|o|u)\s*(\d+\.?\d*))',              # "over 24.5" / "o24.5"
    re.I,
)

# Stat keyword anywhere in the pick: "24.5 pts", "pts o24.5", "over 1.5 HR"
_STAT_KW_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in sorted(_STAT_ALIASES, key=len, reverse=True)) + r')\b',
    re.I,
)

# Over/under line: "o24.5", "over 24.5", "u0.5", "under 1.5"
_LINE_RE = re.compile(r'\b(over|under|o|u)\s*(\d+\.?\d*)\b', re.I)


def parse_player_prop(pick: str) -> dict:
    """
    Extract player prop fields from a pick string.
    Returns a dict with keys: player_name, stat_type, stat_line, over_under.
    All values are None when not found.
    """
    result: dict = {'player_name': None, 'stat_type': None, 'stat_line': None, 'over_under': None}
    if not pick:
        return result

    # Try to extract player name + direction + line together
    m = _PROP_PLAYER_RE.search(pick)
    if m:
        result['player_name'] = m.group(1).strip()
        direction = m.group(2).lower()
        result['over_under'] = 'over' if direction in ('over', 'o') else 'under'
        result['stat_line']   = float(m.group(3))

    # Extract stat keyword
    sk = _STAT_KW_RE.search(pick)
    if sk:
        result['stat_type'] = _STAT_ALIASES.get(sk.group(1).lower())

    # If no player+direction match yet, try standalone line
    if result['over_under'] is None:
        lm = _LINE_RE.search(pick)
        if lm:
            direction = lm.group(1).lower()
            result['over_under'] = 'over' if direction in ('over', 'o') else 'under'
            result['stat_line']   = float(lm.group(2))

    return result


_PROMO_RE = re.compile(
    r'\bget\s+\$\d*'
    r'|\bbet\s*rivers\b'
    r'|\bpromo(?:tion)?\b'
    r'|\bbonus\b'
    r'|\bfree\s+bet\b'
    r'|\bsign\s+up\b'
    r'|\brisk.?free\b'
    r'|\bwelcome\s+(?:offer|bonus)\b'
    r'|\bcash\s+back\b'
    r'|\buse\s+code\b|\bpromo\s+code\b'
    r'|\bopt.?in\b'
    r'|\bno\s+deposit\b'
    r'|\bexclusive\s+offer\b',
    re.I,
)

_BET_SIGNAL_RE = re.compile(
    r'(?<![.\d])[+\-]\d{1,2}(?:\.\d)?\b(?!\d)'
    r'|[+\-]\d{3,4}\b'
    r'|\b(?:over|under)\b'
    r'|\b[ou]\s*\d+\.?\d*\b'
    r'|\bML\b|\bATS\b|\bmoneyline\b|\bparlay\b'
    r'|[+\-]?\d+½',
    re.I,
)


def is_valid_pick(pick_text: str) -> bool:
    """Returns True if pick_text looks like a genuine sports wager."""
    if not pick_text:
        return False
    t = pick_text.strip()
    if _PROMO_RE.search(t):
        return False
    if re.search(r'\b([A-Z]{3,})\s+\1\s+\1\b', t):
        return False
    if not _BET_SIGNAL_RE.search(t) and len(t) < 5:
        return False
    if len(t) < 20 and not _BET_SIGNAL_RE.search(t):
        return False
    return True


def classify_pick_type(pick: str) -> str | None:
    """
    Returns one of: 'props', 'total', 'spread', 'moneyline', or None.
    Order matters — props checked first because e.g. "u2.5 3pt" is a prop total.
    If the pick has odds but no other marker it is treated as a moneyline.
    """
    if not pick:
        return None
    if _PARLAY_RE.search(pick):
        return 'parlay'
    if _PROP_RE.search(pick):
        return 'props'
    if _TOTAL_RE.search(pick):
        return 'total'
    if _HALF_SPREAD_RE.search(pick) or _SPREAD_RE.search(pick):
        return 'spread'
    if _ML_RE.search(pick):
        return 'moneyline'
    # Fallback: if there's a 3-digit odds marker but nothing else matched → moneyline
    if _ODDS_RE.search(pick):
        return 'moneyline'
    return None
