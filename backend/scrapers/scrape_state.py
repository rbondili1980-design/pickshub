"""
Lightweight checkpoint store — persists the last successful scrape time per source.

Stored as JSON in backend/scrape_state.json so it survives backend restarts.
Falls back to None (full scrape) if the file doesn't exist or is corrupted.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("sharpslips.scrape_state")

_STATE_FILE = Path(__file__).parent.parent / "scrape_state.json"


def _load() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def get_last_scraped(source: str) -> datetime | None:
    """Return the UTC datetime of the last successful scrape for *source*, or None."""
    raw = _load().get(source)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def set_last_scraped(source: str, at: datetime | None = None) -> None:
    """Record a successful scrape for *source* (defaults to now UTC)."""
    state = _load()
    ts = (at or datetime.now(timezone.utc))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    state[source] = ts.isoformat()
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        logger.warning(f"Could not write scrape state: {e}")
