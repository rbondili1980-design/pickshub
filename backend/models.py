import os

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./picks.db")

_is_postgres = DATABASE_URL.startswith("postgresql")

if _is_postgres:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
else:
    engine = create_async_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class Pick(Base):
    """
    A single expert pick or user-entered bet from any source.

    bet_scope captures the segment of the game the bet covers:
      full_game | f5 | inning_1 | half_1 | half_2 | q1 | q2 | q3 | q4
      | period_1 | period_2 | period_3 | regulation | live

    For player props, player_name / stat_type / stat_line / over_under are
    populated in addition to the standard pick fields.

    result and edge_score are reserved for future model output and grading.
    """
    __tablename__ = "picks"

    id           = Column(Integer, primary_key=True, index=True)
    source       = Column(String, default="winible")   # "winible" | "action_network"
    expert       = Column(String, nullable=True)
    record       = Column(String, nullable=True)        # e.g. "32-18 (+12.4u)"
    pick         = Column(Text)
    game         = Column(String, nullable=True)
    odds         = Column(String, nullable=True)
    sport        = Column(String, nullable=True)
    units        = Column(String, nullable=True)
    comment      = Column(Text, nullable=True)
    pick_type    = Column(String, nullable=True)        # total | spread | moneyline | props | parlay
    user_note    = Column(Text, nullable=True)

    # Game-segment scope -------------------------------------------------------
    bet_scope    = Column(String, nullable=True)        # full_game | f5 | inning_1 | half_1 | q1 …

    # Player prop fields -------------------------------------------------------
    player_name  = Column(String, nullable=True)        # "M. Trout", "Luka Doncic"
    stat_type    = Column(String, nullable=True)        # HR | K | REB | AST | PTS | YDS | TD …
    stat_line    = Column(Float,  nullable=True)        # numeric line: 0.5, 4.5, 24.5
    over_under   = Column(String, nullable=True)        # "over" | "under"

    # Visibility ---------------------------------------------------------------
    hidden       = Column(Boolean, nullable=False, default=False)  # admin-only: hide from public feed

    # Grading / edge -----------------------------------------------------------
    result       = Column(String, nullable=True)        # pending | win | loss | push | void
    edge_score   = Column(Float,  nullable=True)        # model-generated edge (future)

    session_id   = Column(String, nullable=True)
    posted_at    = Column(String, nullable=True)        # YYYY-MM-DD from source
    scraped_at   = Column(DateTime, default=datetime.utcnow)


class Prop(Base):
    """
    External player prop market lines from third-party feeds (DraftKings, FanDuel,
    PrizePicks, etc.).  Separate from expert picks — these are raw market lines
    used to build the edge model.
    """
    __tablename__ = "props"

    id           = Column(Integer, primary_key=True, index=True)
    source       = Column(String, nullable=False)       # "draftkings" | "fanduel" | "prizepicks" …
    feed_id      = Column(String, nullable=True)        # original ID from the source feed
    sport        = Column(String, nullable=True)
    game         = Column(String, nullable=True)        # "NYY @ BOS"
    game_date    = Column(String, nullable=True)        # YYYY-MM-DD
    player_name  = Column(String, nullable=False)
    team         = Column(String, nullable=True)
    stat_type    = Column(String, nullable=False)       # PTS | REB | HR | K | YDS | TD …
    line         = Column(Float,  nullable=False)       # e.g. 24.5
    over_odds    = Column(String, nullable=True)        # e.g. "-115"
    under_odds   = Column(String, nullable=True)
    bet_scope    = Column(String, nullable=True)        # full_game | half_1 | q1 …
    result       = Column(String, nullable=True)        # pending | win | loss | push | void
    actual_value = Column(Float,  nullable=True)        # post-game actual stat value
    edge_score   = Column(Float,  nullable=True)
    fetched_at   = Column(DateTime, default=datetime.utcnow)


class Slip(Base):
    """
    A user-placed bet (betting slip) for P&L tracking.
    Can reference one or more picks / props via a JSON list of IDs.
    """
    __tablename__ = "slips"

    id           = Column(Integer, primary_key=True, index=True)
    label        = Column(String, nullable=True)        # user-given name for the slip
    bet_type     = Column(String, nullable=True)        # single | parlay | same_game_parlay | teaser
    sport        = Column(String, nullable=True)
    game         = Column(String, nullable=True)
    game_date    = Column(String, nullable=True)        # YYYY-MM-DD

    # Bet details
    pick_ids     = Column(Text, nullable=True)          # JSON list of pick.id references
    prop_ids     = Column(Text, nullable=True)          # JSON list of prop.id references
    description  = Column(Text, nullable=True)          # free-text leg summary

    stake        = Column(Float, nullable=True)         # amount wagered (in units or $)
    odds         = Column(String, nullable=True)        # American odds on the slip, e.g. "-110"
    payout       = Column(Float, nullable=True)         # expected payout if win

    result       = Column(String, nullable=True)        # pending | win | loss | push | void
    profit_loss  = Column(Float, nullable=True)         # actual P&L after grading
    edge_score   = Column(Float, nullable=True)

    created_at   = Column(DateTime, default=datetime.utcnow)
    settled_at   = Column(DateTime, nullable=True)


class AppConfig(Base):
    """
    Simple key/value store for app-wide configuration.
    e.g.  key="guest_experts"  value='["CBlez","Prez Bets","Sean Koerner"]'
    """
    __tablename__ = "app_config"

    key   = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if not _is_postgres:
        await _migrate_picks_table()


async def _migrate_picks_table():
    """
    Idempotent migration: add any columns that were added to Pick after the
    initial schema was created.  SQLite does not support IF NOT EXISTS on
    ALTER TABLE ADD COLUMN, so we catch the OperationalError and ignore it.
    """
    new_columns = [
        ("bet_scope",   "TEXT"),
        ("player_name", "TEXT"),
        ("stat_type",   "TEXT"),
        ("stat_line",   "REAL"),
        ("over_under",  "TEXT"),
        ("result",      "TEXT"),
        ("edge_score",  "REAL"),
        ("hidden",      "INTEGER DEFAULT 0"),
    ]
    async with engine.begin() as conn:
        for col, col_type in new_columns:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE picks ADD COLUMN {col} {col_type}"
                    )
                )
            except Exception:
                pass  # column already exists
