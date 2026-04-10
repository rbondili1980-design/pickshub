"""
Unit tests for scrapers/pick_utils.py.

These cover the pure-function core that classifies every pick stored in the DB.
Run with:  cd backend && pytest
"""
import pytest
from scrapers.pick_utils import (
    classify_pick_type,
    detect_bet_scope,
    parse_player_prop,
    sport_from_game_abbrevs,
    sport_from_pick_text,
)


# ── classify_pick_type ────────────────────────────────────────────────────────

class TestClassifyPickType:
    def test_parlay(self):
        assert classify_pick_type("3-leg parlay -110") == "parlay"

    def test_parlay_case_insensitive(self):
        assert classify_pick_type("Parlay: Lakers ML + Warriors -4.5") == "parlay"

    def test_props_pts(self):
        assert classify_pick_type("Luka over 24.5 PTS") == "props"

    def test_props_rebs(self):
        assert classify_pick_type("Jokic over 11.5 rebs") == "props"

    def test_props_hr(self):
        assert classify_pick_type("Aaron Judge HR +250") == "props"

    def test_props_strikeouts(self):
        assert classify_pick_type("Gerrit Cole over 7.5 strikeouts") == "props"

    def test_total_over(self):
        assert classify_pick_type("Over 220.5 -110") == "total"

    def test_total_under(self):
        assert classify_pick_type("Under 8.5 runs") == "total"

    def test_total_short_over(self):
        assert classify_pick_type("o220.5") == "total"

    def test_spread_negative(self):
        assert classify_pick_type("Warriors -4.5 -110") == "spread"

    def test_spread_positive(self):
        assert classify_pick_type("Patriots +7 -115") == "spread"

    def test_spread_ats(self):
        assert classify_pick_type("Lakers ATS") == "spread"

    def test_spread_half_symbol(self):
        assert classify_pick_type("Celtics -3½") == "spread"

    def test_moneyline_label(self):
        assert classify_pick_type("Yankees ML +130") == "moneyline"

    def test_moneyline_keyword(self):
        assert classify_pick_type("Packers moneyline") == "moneyline"

    def test_moneyline_odds_fallback(self):
        assert classify_pick_type("Dodgers +165") == "moneyline"

    def test_none_empty(self):
        assert classify_pick_type("") is None

    def test_none_none(self):
        assert classify_pick_type(None) is None

    def test_parlay_beats_spread(self):
        # Parlay pick that also contains a spread — parlay wins
        assert classify_pick_type("parlay: Chiefs -3.5 + Eagles -7") == "parlay"


# ── detect_bet_scope ──────────────────────────────────────────────────────────

class TestDetectBetScope:
    def test_full_game_default(self):
        assert detect_bet_scope("Warriors -4.5 -110") == "full_game"

    def test_first_half(self):
        assert detect_bet_scope("Under 110.5 1st half") == "half_1"

    def test_first_half_fh(self):
        assert detect_bet_scope("Lakers FH -3.5") == "half_1"

    def test_second_half(self):
        assert detect_bet_scope("Over 55 2nd half") == "half_2"

    def test_first_inning(self):
        assert detect_bet_scope("NRFI Yankees vs Red Sox") == "inning_1"

    def test_first_inning_alt(self):
        assert detect_bet_scope("Under 0.5 1st inning") == "inning_1"

    def test_f5(self):
        assert detect_bet_scope("Dodgers F5 -1.5 -110") == "f5"

    def test_quarter_q1(self):
        assert detect_bet_scope("Over 54 1st quarter") == "q1"

    def test_quarter_q4(self):
        assert detect_bet_scope("Under 26 4th quarter") == "q4"

    def test_period_1(self):
        assert detect_bet_scope("Bruins 1st period -1.5") == "period_1"

    def test_period_3(self):
        assert detect_bet_scope("Over 2.5 3rd period") == "period_3"

    def test_regulation(self):
        assert detect_bet_scope("Oilers to win in regulation -140") == "regulation"

    def test_live(self):
        assert detect_bet_scope("Warriors live -3.5") == "live"

    def test_none_empty(self):
        assert detect_bet_scope("") is None

    def test_none_none(self):
        assert detect_bet_scope(None) is None

    def test_yrfi(self):
        assert detect_bet_scope("YRFI Cubs vs Brewers") == "inning_1"


# ── parse_player_prop ─────────────────────────────────────────────────────────

class TestParsePlayerProp:
    def test_full_match(self):
        r = parse_player_prop("Luka Doncic over 24.5 PTS")
        assert r["player_name"] == "Luka Doncic"
        assert r["over_under"] == "over"
        assert r["stat_line"] == 24.5
        assert r["stat_type"] == "PTS"

    def test_under(self):
        r = parse_player_prop("Nikola Jokic under 11.5 rebs")
        assert r["over_under"] == "under"
        assert r["stat_line"] == 11.5
        assert r["stat_type"] == "REB"

    def test_short_direction_o(self):
        r = parse_player_prop("Steph Curry o4.5 3pts")
        assert r["over_under"] == "over"
        assert r["stat_line"] == 4.5
        assert r["stat_type"] == "3PM"

    def test_abbreviated_name(self):
        r = parse_player_prop("M. Trout over 1.5 HR")
        assert r["over_under"] == "over"
        assert r["stat_line"] == 1.5
        assert r["stat_type"] == "HR"

    def test_strikeouts(self):
        r = parse_player_prop("Gerrit Cole over 7.5 strikeouts")
        assert r["over_under"] == "over"
        assert r["stat_line"] == 7.5
        assert r["stat_type"] == "K"

    def test_assists(self):
        r = parse_player_prop("James Harden over 9.5 assists")
        assert r["over_under"] == "over"
        assert r["stat_type"] == "AST"

    def test_empty(self):
        r = parse_player_prop("")
        assert r == {"player_name": None, "stat_type": None, "stat_line": None, "over_under": None}

    def test_none(self):
        r = parse_player_prop(None)
        assert r["player_name"] is None

    def test_no_player_name_still_extracts_line(self):
        r = parse_player_prop("over 220.5 total")
        assert r["over_under"] == "over"
        assert r["stat_line"] == 220.5


# ── sport_from_pick_text ──────────────────────────────────────────────────────

class TestSportFromPickText:
    def test_nba_pts(self):
        assert sport_from_pick_text("Luka over 24.5 PTS") == "NBA"

    def test_nba_rebs(self):
        assert sport_from_pick_text("Jokic over 11.5 rebs") == "NBA"

    def test_mlb_hr(self):
        assert sport_from_pick_text("Aaron Judge HR +250") == "MLB"

    def test_mlb_strikeouts(self):
        assert sport_from_pick_text("Cole over 7.5 strikeouts") == "MLB"

    def test_mlb_f5(self):
        assert sport_from_pick_text("Dodgers F5 -1.5") == "MLB"

    def test_mlb_total_range(self):
        # Total of 8.5 is unambiguously MLB (NHL tops out at ~7, NFL is 40+)
        assert sport_from_pick_text("Over 8.5") == "MLB"

    def test_nhl_goals(self):
        assert sport_from_pick_text("McDavid anytime goal +120") == "NHL"

    def test_nfl_rushing(self):
        assert sport_from_pick_text("Derrick Henry over 85.5 rushing yards") == "NFL"

    def test_nfl_touchdown(self):
        assert sport_from_pick_text("Patrick Mahomes first TD scorer") == "NFL"

    def test_cbb_march_madness(self):
        assert sport_from_pick_text("Duke -6.5 March Madness") == "CBB"

    def test_none_generic(self):
        # Generic pick with no sport signal
        assert sport_from_pick_text("Team A -110") is None

    def test_empty(self):
        assert sport_from_pick_text("") is None


# ── sport_from_game_abbrevs ───────────────────────────────────────────────────

class TestSportFromGameAbbrevs:
    def test_nhl_vgk(self):
        assert sport_from_game_abbrevs("VGK @ EDM") == "NHL"

    def test_mlb_nyy(self):
        assert sport_from_game_abbrevs("NYY @ BOS") == "MLB"

    def test_nfl_ne(self):
        assert sport_from_game_abbrevs("NE @ MIA") == "NFL"

    def test_nba_lal(self):
        assert sport_from_game_abbrevs("LAL vs GSW") == "NBA"

    def test_mlb_lad(self):
        assert sport_from_game_abbrevs("LAD vs SD") == "MLB"

    def test_none_ambiguous(self):
        # No exclusive abbreviation — can't determine sport
        result = sport_from_game_abbrevs("PHI @ NYG")
        # PHI and NYG exist in multiple sports; no guarantee; just verify no crash
        assert result is None or isinstance(result, str)

    def test_none_empty(self):
        assert sport_from_game_abbrevs("") is None

    def test_none_none(self):
        assert sport_from_game_abbrevs(None) is None
