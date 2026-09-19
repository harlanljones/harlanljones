#!/usr/bin/env python3
"""
MLB Birthday Almanac Generator
Fetches MLB players born on the current (or specified) calendar day, computes
sabermetric superlatives, and injects a clean markdown ledger into README.md.
Zero third-party dependencies (standard library only).
"""

import argparse
import base64
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svg_cards import (  # noqa: E402
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    TITLE_COLOR,
    card_shell,
    esc,
    plain_text,
    text_width,
    wrap_by_width,
)

DUGOUT_SVG_URL = (
    "https://raw.githubusercontent.com/harlanljones/harlanljones"
    "/profile-cards/dugout-dispatch.svg"
)

CATEGORY_ACCENTS = {
    "WARrior": "#58a6ff",
    "Immaculate Grid Gem": "#a371f7",
    "Antique Ace": "#f78166",
    "Long Ball Laureate": "#3fb950",
    "Strikeout Savant": "#f778ba",
    "Speed Superlative": "#e3b341",
}

# Primary brand colors by Stats API team abbreviation. Minor-league
# affiliates not listed here fall back to their parent MLB org color.
MLB_TEAM_COLORS = {
    "ARI": "#A7194B", "ATH": "#003831", "ATL": "#CE1148", "BAL": "#DF4601",
    "BOS": "#BD3039", "CHC": "#0E3386", "CWS": "#27251F", "CIN": "#C6011F",
    "CLE": "#00385D", "COL": "#33006F", "DET": "#0C2340", "HOU": "#EB6E1F",
    "KC": "#004687", "LAA": "#BA0021", "LAD": "#005A9C", "MIA": "#00A3E0",
    "MIL": "#FFC52F", "MIN": "#002B5C", "NYY": "#003087", "PHI": "#E81828",
    "PIT": "#FDB827", "SD": "#FFC425", "SEA": "#0C2C56", "SF": "#FD5A1E",
    "STL": "#C41E3A", "TB": "#092C5C", "TEX": "#003278", "TOR": "#134A8E",
    "WSH": "#AB0003",
}

AAA_TEAM_COLORS = {
    "ABQ": "#CE0E2D", "BUF": "#004684", "CLT": "#232323", "COL": "#0B2C54",
    "DUR": "#1B3A5D", "ELP": "#AA1E2E", "GWN": "#041E42", "IND": "#A6192E",
    "IOW": "#0E3386", "JAX": "#007A87", "LHV": "#7A1F2B", "LOU": "#00543D",
    "LV": "#00263A", "MEM": "#D31145", "NAS": "#B01E24", "NOR": "#E35B00",
    "OKC": "#003DA5", "OMA": "#004B8D", "RNO": "#B11B2D", "ROC": "#C8102E",
    "RR": "#BF0D3E", "SAC": "#E85D2A", "SCR": "#0C2340", "SL": "#EAAA00",
    "STP": "#0057B8", "SUG": "#042244", "SYR": "#FF5910", "TAC": "#00685E",
    "TOL": "#0A3D62", "WOR": "#BD3039",
}


def contrast_text(hex_color: str) -> str:
    """Dark or white text, whichever reads on the given fill."""
    h = hex_color.lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return "#0d1117"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#0d1117" if luminance > 0.55 else "#ffffff"


def team_fill(team: str, mlb_org: str, is_mlb: bool) -> str:
    """Pill fill matching the player's club: MLB team color on MLB
    rosters, affiliate color in the minors, parent-org color as fallback."""
    team = (team or "").upper()
    mlb_org = (mlb_org or "").upper()
    if is_mlb:
        return MLB_TEAM_COLORS.get(team, "#3fb950")
    return AAA_TEAM_COLORS.get(team) or MLB_TEAM_COLORS.get(mlb_org, "#e3b341")


def fetch_json(url: str, timeout: int = 15) -> Dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


_statsapi_cache: Dict[str, Any] = {}
_mlb_abbrev_cache: Dict[str, str] = {}


def fetch_mlb_abbrev(team_id: Any) -> str:
    """MLB club abbreviation for a Stats API team id (used to map a minor
    league affiliate back to its parent organization)."""
    key = str(team_id)
    if key in _mlb_abbrev_cache:
        return _mlb_abbrev_cache[key]
    abbrev = ""
    try:
        teams = fetch_json(f"https://statsapi.mlb.com/api/v1/teams/{key}").get("teams", [{}])
        abbrev = teams[0].get("abbreviation") or ""
    except Exception as e:
        print(f"Notice: could not resolve MLB abbrev for team {key}: {e}", file=sys.stderr)
    _mlb_abbrev_cache[key] = abbrev
    return abbrev


_person_id_cache: Dict[str, Optional[int]] = {}


def resolve_person_id(name: str, birth_year: int, include_inactive: bool = False) -> Optional[int]:
    """MLB Stats API person id for a player, disambiguated by birth year.

    Active players first; optionally fall back to inactive matches (used
    only for headshot lookup of retired featured players).
    """
    cache_key = f"{name}|{birth_year}|{include_inactive}"
    if cache_key in _person_id_cache:
        return _person_id_cache[cache_key]
    pid: Optional[int] = None
    try:
        search_url = "https://statsapi.mlb.com/api/v1/people/search?names=" + urllib.parse.quote(name)
        people = fetch_json(search_url).get("people", [])
        matches = [p for p in people if p.get("isPlayer")
                   and str(p.get("birthDate", ""))[:4] == str(birth_year)]
        active = [p for p in matches if p.get("active")]
        pool = active or (matches if include_inactive else [])
        if len(pool) == 1:
            pid = pool[0]["id"]
    except Exception as e:
        print(f"Notice: could not resolve person id for {name}: {e}", file=sys.stderr)
    _person_id_cache[cache_key] = pid
    return pid


_headshot_cache: Dict[str, str] = {}


def download_image_as_data_uri(url: str, max_bytes: int = 300000) -> str:
    """Fetch a remote image as a data URI ("" on any failure)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = resp.headers.get_content_type()
            raw = resp.read()
            if resp.status == 200 and ctype in ("image/jpeg", "image/png", "image/webp") \
                    and 500 < len(raw) < max_bytes:
                return f"data:{ctype};base64," + base64.b64encode(raw).decode("ascii")
    except Exception as e:
        print(f"Notice: image download failed for {url[:80]}: {e}", file=sys.stderr)
    return ""


def _ascii_fold(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def _wiki_json(url: str) -> Dict[str, Any]:
    """GET via the Wikipedia API with an identifying UA and a politeness
    delay (generic rapid-fire callers get HTTP 429)."""
    time.sleep(1.0)
    req = urllib.request.Request(url, headers={
        "User-Agent": "DugoutDispatch/1.0 (https://github.com/harlanljones/harlanljones)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_wikipedia_portrait(name: str, size: int = 128) -> str:
    """Portrait thumbnail via the Wikipedia API (covers retired players
    MLBAM no longer hosts). Matches the ballplayer's article by surname
    guard; "" when no suitable portrait exists."""
    try:
        query = urllib.parse.quote(f"{name} baseball")
        search = _wiki_json(
            "https://en.wikipedia.org/w/api.php?action=query&format=json"
            f"&list=search&srsearch={query}&srlimit=3"
        )
        results = (search.get("query") or {}).get("search") or []
        if not results:
            return ""
        title = results[0].get("title", "")
        surname = _ascii_fold(name.strip().split()[-1])
        if surname not in _ascii_fold(title):
            return ""
        page = urllib.parse.quote(title)
        detail = _wiki_json(
            "https://en.wikipedia.org/w/api.php?action=query&format=json"
            f"&prop=pageimages&titles={page}&pithumbsize={size}&redirects=1"
        )
        pages = ((detail.get("query") or {}).get("pages")) or {}
        for entry in pages.values():
            thumb = (entry.get("thumbnail") or {}).get("source") or ""
            if thumb and not thumb.lower().endswith(".svg"):
                data_uri = download_image_as_data_uri(thumb)
                if data_uri:
                    return data_uri
    except Exception as e:
        print(f"Notice: wikipedia portrait failed for {name}: {e}", file=sys.stderr)
    return ""


def fetch_headshot_b64(person_id: Any, player_name: str = "") -> str:
    """Embedded data-URI headshot for a player ("" when none).

    MLBAM first (current players), then Wikipedia portraits (retired
    players). Remote images never load inside SVGs served through <img>,
    so avatars are embedded at generation time; missing portraits fall
    back to initials rendered by the caller.
    """
    key = f"{person_id}|{player_name}"
    if key in _headshot_cache:
        return _headshot_cache[key]
    b64 = ""
    if person_id:
        url = (
            "https://img.mlbstatic.com/mlb-images/image/upload/"
            "d_people:generic:headshot:67:current.png/"
            f"w_128,q_auto:best/v1/people/{person_id}/headshot/67/current"
        )
        b64 = download_image_as_data_uri(url)
    if not b64 and player_name:
        b64 = fetch_wikipedia_portrait(player_name)
    _headshot_cache[key] = b64
    return b64


def player_initials(name: str) -> str:
    parts = [w for w in re.sub(r"[^A-Za-z .'-]", "", name).split() if w]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def resolve_current_org(name: str, birth_year: int) -> Dict[str, Any]:
    """Resolve a player's current organization via the MLB Stats API.

    Returns a dict with:
      team      - current team abbreviation (e.g. "TOR" or "CLT")
      mlb_org   - parent MLB club abbreviation (same as team when MLB)
      is_mlb    - True when currentTeam plays in Major League Baseball
                  (sport id 1); False for Triple-A/minors or unknown.
      person_id - MLB Stats API person id (None when unmatched).
      ("FA" handling is left to the caller: empty team means unsigned.)
    """
    cache_key = f"{name}|{birth_year}"
    if cache_key in _statsapi_cache:
        return _statsapi_cache[cache_key]  # type: ignore[return-value]

    result: Dict[str, Any] = {"team": "", "mlb_org": "", "is_mlb": False, "person_id": None}
    try:
        pid = resolve_person_id(name, birth_year)
        result["person_id"] = pid
        if pid is not None:
            detail = fetch_json(f"https://statsapi.mlb.com/api/v1/people/{pid}?hydrate=currentTeam")
            person = detail.get("people", [{}])[0]
            current = person.get("currentTeam") or {}
            team_id = current.get("id")
            if team_id:
                # Bare currentTeam hydration only carries id/name/link, so
                # fetch the canonical team record (abbreviation, sport,
                # parentOrgId) from the teams endpoint.
                full = fetch_json(f"https://statsapi.mlb.com/api/v1/teams/{team_id}").get("teams", [{}])[0]
                abbrev = full.get("abbreviation") or current.get("name", "")
                sport_id = (full.get("sport") or {}).get("id")
                if sport_id == 1:
                    result = {"team": abbrev, "mlb_org": abbrev, "is_mlb": True, "person_id": pid}
                else:
                    parent_id = full.get("parentOrgId")
                    mlb_abbrev = fetch_mlb_abbrev(parent_id) if parent_id else ""
                    result = {"team": abbrev, "mlb_org": mlb_abbrev, "is_mlb": False, "person_id": pid}
    except Exception as e:
        print(f"Notice: could not resolve current org for {name}: {e}", file=sys.stderr)

    _statsapi_cache[cache_key] = result
    return result


def fetch_birthday_html(month: int, day: int) -> str:
    url = f"https://www.baseball-reference.com/friv/birthdays.cgi?month={month}&day={day}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_float(val: str, default: float = 0.0) -> float:
    try:
        val = val.strip().replace(",", "")
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def parse_int(val: str, default: int = 0) -> int:
    try:
        val = val.strip().replace(",", "")
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def parse_players(html: str) -> List[Dict[str, Any]]:
    players: List[Dict[str, Any]] = []
    
    # Locate the table body inside birthday_stats
    table_match = re.search(r'<table[^>]*id=["\']birthday_stats["\'][^>]*>(.*?)</table>', html, re.DOTALL)
    if not table_match:
        # Fallback: search anywhere for rows with data-stat="player"
        row_matches = re.findall(r'<tr\s*>(.*?)</tr>', html, re.DOTALL)
    else:
        tbody_match = re.search(r'<tbody>(.*?)</tbody>', table_match.group(1), re.DOTALL)
        content = tbody_match.group(1) if tbody_match else table_match.group(1)
        row_matches = re.findall(r'<tr\s*>(.*?)</tr>', content, re.DOTALL)

    for row in row_matches:
        if 'data-stat="player"' not in row:
            continue

        def get_stat(stat_name: str) -> str:
            m = re.search(rf'data-stat=["\']{re.escape(stat_name)}["\'][^>]*>(.*?)</td>', row, re.DOTALL)
            if not m:
                # Some might be th or have slightly different tag structure
                m = re.search(rf'data-stat=["\']{re.escape(stat_name)}["\'][^>]*>(.*?)</th>', row, re.DOTALL)
            if not m:
                return ""
            raw = m.group(1)
            # Strip tags
            cleaned = re.sub(r'<[^>]+>', '', raw).strip()
            return cleaned

        name_match = re.search(r'data-stat=["\']player["\'][^>]*>.*?<a\s+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', row, re.DOTALL)
        if not name_match:
            continue

        href = name_match.group(1)
        name = name_match.group(2).strip()

        # Clean potential asterisk / plus / pound signs
        clean_name = re.sub(r'[*+#]+$', '', name).strip()
        is_hof = '+' in name
        
        bref_url = f"https://www.baseball-reference.com{href}" if href.startswith('/') else href

        birth_year = parse_int(get_stat("birth_year"))
        experience = parse_int(get_stat("experience"))
        year_min = parse_int(get_stat("year_min"))
        year_max = parse_int(get_stat("year_max"))
        war = parse_float(get_stat("WAR"))
        allstar_games = parse_int(get_stat("allstar_games"))
        
        # Batting
        games = parse_int(get_stat("G"))
        ab = parse_int(get_stat("AB"))
        runs = parse_int(get_stat("R"))
        hits = parse_int(get_stat("H"))
        hr = parse_int(get_stat("HR"))
        rbi = parse_int(get_stat("RBI"))
        sb = parse_int(get_stat("SB"))
        bb = parse_int(get_stat("BB"))
        ba = get_stat("batting_avg")
        obp = get_stat("onbase_perc")
        slg = get_stat("slugging_perc")
        ops = get_stat("onbase_plus_slugging")
        ops_plus = get_stat("onbase_plus_slugging_plus")

        # Pitching
        wins = parse_int(get_stat("W"))
        losses = parse_int(get_stat("L"))
        era = get_stat("earned_run_avg")
        era_plus = get_stat("earned_run_avg_plus")
        whip = get_stat("whip")
        g_p = parse_int(get_stat("G_p"))
        gs = parse_int(get_stat("GS"))
        sv = parse_int(get_stat("SV"))
        ip = get_stat("IP")
        so_p = parse_int(get_stat("SO_p"))
        franchises_raw = get_stat("franchises")

        franchises = [f.strip() for f in franchises_raw.split(',') if f.strip()] if franchises_raw else []

        # Determine primary role: pitchers typically have far more pitching appearances than at-bats (or negligible at-bats)
        # Position players who pitched in blowouts or converted sluggers (like Babe Ruth) have ab >> g_p
        is_pitcher = (g_p > 0 and (ab < 500 or g_p > (ab // 2)))

        players.append({
            "name": clean_name,
            "raw_name": name,
            "bref_url": bref_url,
            "birth_year": birth_year,
            "experience": experience,
            "year_min": year_min,
            "year_max": year_max,
            "war": war,
            "allstar_games": allstar_games,
            "is_hof": is_hof,
            "is_pitcher": is_pitcher,
            "games": games,
            "ab": ab,
            "runs": runs,
            "hits": hits,
            "hr": hr,
            "rbi": rbi,
            "sb": sb,
            "bb": bb,
            "ba": ba,
            "obp": obp,
            "slg": slg,
            "ops": ops,
            "ops_plus": ops_plus,
            "wins": wins,
            "losses": losses,
            "era": era,
            "era_plus": era_plus,
            "whip": whip,
            "g_p": g_p,
            "gs": gs,
            "sv": sv,
            "ip": ip,
            "so_p": so_p,
            "franchises": franchises,
            "franchises_raw": franchises_raw,
        })

    return players


def span_label(p: Dict[str, Any], current_year: int) -> str:
    if p["year_min"] == p["year_max"]:
        return f"{p['year_min']}"
    if p["year_max"] >= (current_year - 1):
        return f"{p['year_min']}–Pres"
    return f"{p['year_min']}–{p['year_max']}"


def franchise_label(p: Dict[str, Any], max_display: int = 5) -> str:
    if not p["franchises"]:
        return "—"
    if len(p["franchises"]) <= max_display:
        return ", ".join(p["franchises"])
    return ", ".join(p["franchises"][:max_display]) + f" (+{len(p['franchises']) - max_display})"


def display_name(p: Dict[str, Any]) -> str:
    return p["name"] + (" (HOF)" if p["is_hof"] else "")


def war_metrics_text(p: Dict[str, Any]) -> str:
    parts = [f"{p['war']:.1f} bWAR"]
    if p["is_pitcher"]:
        if p["era"]:
            parts.append(f"{p['era']} ERA")
        if p["wins"] > 0 or p["losses"] > 0:
            parts.append(f"{p['wins']}-{p['losses']} W-L")
        if p["so_p"] > 0:
            parts.append(f"{p['so_p']:,} SO")
        if p["sv"] > 10:
            parts.append(f"{p['sv']} SV")
    else:
        if p["ops"] and p["ops"].strip():
            parts.append(f".{p['ops'].lstrip('0.')} OPS" if p["ops"].startswith("0.") else f"{p['ops']} OPS")
        if p["hr"] > 0:
            parts.append(f"{p['hr']} HR")
        if p["hits"] > 0:
            parts.append(f"{p['hits']:,} H")
        if p["sb"] > 25:
            parts.append(f"{p['sb']} SB")
    return " • ".join(parts)


def polymath_metrics_text(p: Dict[str, Any]) -> str:
    team_count = len(p["franchises"])
    teams_str = ", ".join(p["franchises"][:6]) + ("..." if len(p["franchises"]) > 6 else "")
    return f"{team_count} Clubs ({teams_str}) • {p['war']:.1f} bWAR • {p['experience']} Yrs — a true Immaculate Grid cheat code"


def vintage_metrics_text(p: Dict[str, Any]) -> str:
    age_notes = f"Born {p['birth_year']}"
    parts = [age_notes, f"{p['experience']} Seasons", f"{p['war']:.1f} bWAR"]
    if p["is_pitcher"] and p["g_p"] > 0:
        parts.append(f"{p['g_p']} G ({p['gs']} GS)")
    elif p["hits"] > 0:
        parts.append(f"{p['hits']:,} H")
    return " • ".join(parts)


def format_cohort_tag(p: Dict[str, Any]) -> Tuple[str, bool]:
    """(display_tag, is_mlb) for one active player.

    MLB roster members get a bare club tag ("TOR"); minor leaguers keep
    their affiliate plus parent MLB org ("CLT · CWS org"); unresolvable
    players fall back to the BRef franchise or FA.
    """
    org = resolve_current_org(p["name"], p["birth_year"])
    team = (org.get("team") or "").upper()
    mlb_org = (org.get("mlb_org") or "").upper()
    if org.get("is_mlb") and team:
        return team, True
    if team and mlb_org:
        return f"{team} · {mlb_org} org", False
    if team:
        return f"{team} · minors", False
    fallback = p["franchises"][-1] if p["franchises"] else ""
    if not fallback or fallback.upper() == "TBD":
        return "FA", False
    return fallback, False


def resolve_active_cohort(active_players: List[Dict[str, Any]]) -> Dict[str, List]:
    """Split active players into MLB-roster and minor-league groups.

    Each group holds entry dicts {player, tag, is_mlb, team, mlb_org,
    person_id}, sorted by career WAR.
    """
    mlb: List[Dict[str, Any]] = []
    minors: List[Dict[str, Any]] = []
    for ap in active_players:
        org = resolve_current_org(ap["name"], ap["birth_year"])
        tag, is_mlb = format_cohort_tag(ap)
        entry = {
            "player": ap,
            "tag": tag,
            "is_mlb": is_mlb,
            "team": (org.get("team") or "").upper(),
            "mlb_org": (org.get("mlb_org") or "").upper(),
            "person_id": org.get("person_id"),
            "initials": player_initials(ap["name"]),
            "img": fetch_headshot_b64(org.get("person_id"), ap["name"]),
        }
        (mlb if is_mlb else minors).append(entry)
    return {"mlb": mlb, "minors": minors}


def build_daily_ledger(players: List[Dict[str, Any]], month: int, day: int, current_year: int) -> str:
    month_name = datetime.date(2024, month, day).strftime("%B")
    date_str = f"{month_name} {day}"

    if not players:
        return f"### Daily Dugout Dispatch: {date_str}\n\n*No MLB player birth records indexed for this date.*\n"

    # 1. WARrior (career WAR leader)
    war_leader = max(players, key=lambda p: p["war"])

    # 2. Immaculate Grid Gem (most distinct franchises)
    polymath = max(players, key=lambda p: len(p["franchises"]))

    # 3. Antique Ace (earliest-born player)
    valid_birth_years = [p for p in players if p["birth_year"] > 1800]
    vintage = min(valid_birth_years, key=lambda p: p["birth_year"]) if valid_birth_years else players[-1]

    # 4. Superlatives
    hr_leader = max(players, key=lambda p: p["hr"])
    sb_leader = max(players, key=lambda p: p["sb"])
    so_leader = max(players, key=lambda p: p["so_p"])

    # 5. Active cohort (on MLB active rosters this season)
    active_players = [p for p in players if p["year_max"] >= current_year]
    active_players.sort(key=lambda p: p["war"], reverse=True)

    # Format metrics helper
    def format_span(p: Dict[str, Any]) -> str:
        return span_label(p, current_year)

    def format_player_link(p: Dict[str, Any]) -> str:
        name_str = p["name"]
        if p["is_hof"]:
            name_str += " (HOF)"
        return f"[{name_str}]({p['bref_url']})"

    def format_war_metrics(p: Dict[str, Any]) -> str:
        return war_metrics_text(p)

    def format_polymath_metrics(p: Dict[str, Any]) -> str:
        return polymath_metrics_text(p)

    def format_vintage_metrics(p: Dict[str, Any]) -> str:
        return vintage_metrics_text(p)

    def format_franchises(p: Dict[str, Any], max_display: int = 5) -> str:
        return franchise_label(p, max_display)

    # Build markdown table
    lines = [
        f"### Daily Dugout Dispatch: {date_str}",
        "",
        "| Category | Player | Active Span | Franchise(s) | Key Sabermetrics |",
        "| :--- | :--- | :--- | :--- | :--- |",
        f"| **WARrior** | {format_player_link(war_leader)} | {format_span(war_leader)} | {format_franchises(war_leader)} | {format_war_metrics(war_leader)} |",
        f"| **Immaculate Grid Gem** | {format_player_link(polymath)} | {format_span(polymath)} | {len(polymath['franchises'])} Clubs | {format_polymath_metrics(polymath)} |",
        f"| **Antique Ace** | {format_player_link(vintage)} | {format_span(vintage)} | {format_franchises(vintage)} | {format_vintage_metrics(vintage)} |",
    ]

    # Add superlatives if valid
    if hr_leader["hr"] > 15:
        lines.append(f"| **Long Ball Laureate** | {format_player_link(hr_leader)} | {format_span(hr_leader)} | {format_franchises(hr_leader)} | {hr_leader['hr']} Career HR • {hr_leader['rbi']} RBI |")
    if so_leader["so_p"] > 100:
        lines.append(f"| **Strikeout Savant** | {format_player_link(so_leader)} | {format_span(so_leader)} | {format_franchises(so_leader)} | {so_leader['so_p']:,} Strikeouts • {so_leader['era']} ERA |")
    elif sb_leader["sb"] > 50:
        lines.append(f"| **Speed Superlative** | {format_player_link(sb_leader)} | {format_span(sb_leader)} | {format_franchises(sb_leader)} | {sb_leader['sb']} Stolen Bases • {sb_leader['hits']:,} H |")

    lines.append("")
    
    # Active Player roster note if present (MLB clubs vs minors w/ parent org).
    if active_players:
        cohort = resolve_active_cohort(active_players)
        mlb_names = [f"{format_player_link(e['player'])} ({e['tag']})" for e in cohort["mlb"]]
        minor_names = [f"{format_player_link(e['player'])} ({e['tag']})" for e in cohort["minors"]]
        if mlb_names:
            lines.append(f"*On MLB rosters today ({len(mlb_names)}):* {', '.join(mlb_names)}")
        if minor_names:
            lines.append(f"*Also active in the minors ({len(minor_names)}):* {', '.join(minor_names)}")
        if mlb_names or minor_names:
            lines.append("")

    lines.append(f"*Historical index contains {len(players)} total Major League Baseball players born on {date_str}.*")
    lines.append("")

    return "\n".join(lines)


def build_dispatch_model(players: List[Dict[str, Any]], month: int, day: int, current_year: int) -> Dict[str, Any]:
    """Shared dispatch model feeding both the markdown ledger and the SVG card.

    Featured rows hold plain-text {category, name, span, franchises, metrics};
    cohort groups hold (player, display_tag) tuples split by MLB vs minors.
    """
    month_name = datetime.date(2024, month, day).strftime("%B")
    date_str = f"{month_name} {day}"
    if not players:
        return {"date_str": date_str, "empty": True, "featured": [], "mlb": [], "minors": [], "total": 0}

    war_leader = max(players, key=lambda p: p["war"])
    polymath = max(players, key=lambda p: len(p["franchises"]))
    valid_birth_years = [p for p in players if p["birth_year"] > 1800]
    vintage = min(valid_birth_years, key=lambda p: p["birth_year"]) if valid_birth_years else players[-1]
    hr_leader = max(players, key=lambda p: p["hr"])
    sb_leader = max(players, key=lambda p: p["sb"])
    so_leader = max(players, key=lambda p: p["so_p"])

    def row(category: str, p: Dict[str, Any], metrics: str, franchises: Optional[str] = None) -> Dict[str, str]:
        name = display_name(p)
        return {
            "category": category,
            "name": name,
            "span": span_label(p, current_year),
            "franchises": franchises if franchises is not None else franchise_label(p),
            "metrics": metrics,
            "initials": player_initials(name),
            "img": fetch_headshot_b64(
                resolve_person_id(p["name"], p["birth_year"], include_inactive=True), p["name"]
            ),
        }

    featured = [
        row("WARrior", war_leader, war_metrics_text(war_leader)),
        row("Immaculate Grid Gem", polymath, polymath_metrics_text(polymath),
            f"{len(polymath['franchises'])} Clubs"),
        row("Antique Ace", vintage, vintage_metrics_text(vintage)),
    ]
    if hr_leader["hr"] > 15:
        featured.append(row("Long Ball Laureate", hr_leader,
                             f"{hr_leader['hr']} Career HR • {hr_leader['rbi']} RBI"))
    if so_leader["so_p"] > 100:
        featured.append(row("Strikeout Savant", so_leader,
                             f"{so_leader['so_p']:,} Strikeouts • {so_leader['era']} ERA"))
    elif sb_leader["sb"] > 50:
        featured.append(row("Speed Superlative", sb_leader,
                             f"{sb_leader['sb']} Stolen Bases • {sb_leader['hits']:,} H"))

    active_players = [p for p in players if p["year_max"] >= current_year]
    active_players.sort(key=lambda p: p["war"], reverse=True)
    cohort = resolve_active_cohort(active_players)

    return {
        "date_str": date_str,
        "empty": False,
        "featured": featured,
        "mlb": cohort["mlb"],
        "minors": cohort["minors"],
        "total": len(players),
    }


def _avatar_svg(uid: str, cx: float, cy: float, r: float, img: str, initials: str, fallback_fill: str) -> str:
    """Circular avatar: embedded headshot when available, else initials."""
    if img:
        return (
            f'<defs><clipPath id="{uid}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}"/></clipPath></defs>'
            f'<image href="{img}" x="{cx - r:.1f}" y="{cy - r:.1f}" '
            f'width="{2 * r:.1f}" height="{2 * r:.1f}" clip-path="url(#{uid})" preserveAspectRatio="xMidYMid slice"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{BORDER}" stroke-width="1.5"/>'
        )
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fallback_fill}"/>'
        f'<text x="{cx:.1f}" y="{cy + 4.5:.1f}" font-size="11" font-weight="700" '
        f'fill="{contrast_text(fallback_fill)}" text-anchor="middle" font-family="{FONT_FAMILY}">{esc(initials)}</text>'
    )


def _avatar_pills(x: float, y: float, entries: List[Dict[str, str]], max_x: float) -> Tuple[str, float]:
    """Flowing pills with circular avatars. Each entry holds
    {label, fill, img, initials}. Returns (svg_fragment, height)."""
    frags: List[str] = []
    cx, cy = x, y
    gap, row_h, pill_h, av_d = 8, 34, 28, 22
    for n, e in enumerate(entries):
        label, fill = e["label"], e["fill"]
        w = av_d + 7 + text_width(label, 11.5, bold=True) + 15
        if cx + w > max_x and cx > x:
            cx = x
            cy += row_h
        frags.append(
            f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{pill_h}" '
            f'rx="{pill_h / 2:.1f}" fill="{fill}"/>'
        )
        frags.append(_avatar_svg(f"dgav-{n}", cx + 4 + av_d / 2, cy + pill_h / 2,
                                 av_d / 2, e.get("img", ""), e.get("initials", "?"), BORDER))
        frags.append(
            f'<text x="{cx + 4 + av_d + 6:.1f}" y="{cy + pill_h / 2 + 4:.1f}" font-size="11.5" '
            f'font-weight="700" fill="{contrast_text(fill)}" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        )
        cx += w + gap
    return "\n".join(frags), (cy - y) + pill_h + 6


def render_dugout_svg(model: Dict[str, Any]) -> str:
    """Single house-style SVG card for the Daily Dugout Dispatch.

    Same card_shell / fonts / colors as the skills, projects, weekly and
    activity graphics; embedded in README via an <img> on profile-cards.
    """
    max_x = CARD_WIDTH - PAD_X
    frags: List[str] = []
    cy = 10.0

    if model.get("empty"):
        frags.append(
            f'<text x="{PAD_X}" y="{cy + 14:.1f}" font-size="13" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">No MLB player birth records indexed for this date.</text>'
        )
        return card_shell("Daily Dugout Dispatch", model.get("date_str", ""), "\n".join(frags), cy + 28)

    for i, feat in enumerate(model["featured"]):
        accent = CATEGORY_ACCENTS.get(feat["category"], "#58a6ff")
        cat = feat["category"]
        row_top = cy
        frags.append(_avatar_svg(f"dgfeat-{i}", PAD_X + 20, cy + 20, 20,
                                 feat.get("img", ""), feat.get("initials", "?"), accent))
        tx = PAD_X + 52
        cat_w = text_width(cat, 13, bold=True)
        frags.append(
            f'<text x="{tx:.1f}" y="{cy + 14:.1f}" font-size="13" font-weight="700" '
            f'fill="{accent}" font-family="{FONT_FAMILY}">{esc(cat)}</text>'
            f'<text x="{tx + cat_w + 8:.1f}" y="{cy + 14:.1f}" font-size="14" font-weight="700" '
            f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">{esc(feat["name"])}</text>'
        )
        cy += 22
        frags.append(
            f'<text x="{tx:.1f}" y="{cy + 12:.1f}" font-size="11.5" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">{esc(feat["span"])} · {esc(feat["franchises"])}</text>'
        )
        cy += 19
        for line in wrap_by_width(plain_text(feat["metrics"]), 12.5, max_x - tx, max_lines=2):
            frags.append(
                f'<text x="{tx:.1f}" y="{cy + 12:.1f}" font-size="12.5" fill="{TEXT}" '
                f'font-family="{FONT_FAMILY}">{esc(line)}</text>'
            )
            cy += 18
        cy = max(cy + 8, row_top + 48)
        if i < len(model["featured"]) - 1:
            frags.append(
                f'<line x1="{PAD_X}" y1="{cy:.1f}" x2="{max_x}" y2="{cy:.1f}" '
                f'stroke="{BORDER}" stroke-width="1"/>'
            )
            cy += 14

    # Active cohort, split the way the markdown ledger does.
    if model["mlb"] or model["minors"]:
        frags.append(
            f'<line x1="{PAD_X}" y1="{cy:.1f}" x2="{max_x}" y2="{cy:.1f}" '
            f'stroke="{BORDER}" stroke-width="1"/>'
        )
        cy += 18
        if model["mlb"]:
            frags.append(
                f'<text x="{PAD_X}" y="{cy + 12:.1f}" font-size="13" font-weight="700" '
                f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">On MLB rosters today ({len(model["mlb"])})</text>'
            )
            cy += 22
            entries = [
                {
                    "label": f"{display_name(e['player'])} · {e['tag']}",
                    "fill": team_fill(e["team"], e["mlb_org"], True),
                    "img": e.get("img", ""),
                    "initials": e.get("initials", "?"),
                }
                for e in model["mlb"]
            ]
            pills, pills_h = _avatar_pills(PAD_X, cy, entries, max_x)
            frags.append(pills)
            cy += pills_h + 10
        if model["minors"]:
            frags.append(
                f'<text x="{PAD_X}" y="{cy + 12:.1f}" font-size="13" font-weight="700" '
                f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Also active in the minors ({len(model["minors"])})</text>'
            )
            cy += 22
            entries = [
                {
                    "label": f"{display_name(e['player'])} · {e['tag']}",
                    "fill": team_fill(e["team"], e["mlb_org"], False),
                    "img": e.get("img", ""),
                    "initials": e.get("initials", "?"),
                }
                for e in model["minors"]
            ]
            pills, pills_h = _avatar_pills(PAD_X, cy, entries, max_x)
            frags.append(pills)
            cy += pills_h + 4

    subtitle = f"{model['date_str']} · {model['total']} players in the historical index"
    return card_shell("Daily Dugout Dispatch", subtitle, "\n".join(frags), cy)


def ensure_dugout_image(readme_path: str, svg_url: str = DUGOUT_SVG_URL) -> bool:
    """Point the MLB birthday README block at the rendered SVG card.

    After the first swap the README markup stays static; only the SVG on
    the profile-cards branch changes day to day.
    """
    start_tag = "<!-- MLB_BIRTHDAY_START -->"
    end_tag = "<!-- MLB_BIRTHDAY_END -->"
    if not os.path.exists(readme_path):
        print(f"Error: Target file {readme_path} not found.", file=sys.stderr)
        return False
    with open(readme_path, "r", encoding="utf-8") as f:
        existing = f.read()
    img_tag = f'<img src="{svg_url}" alt="Daily Dugout Dispatch" width="100%" />'
    section = f"{start_tag}\n{img_tag}\n{end_tag}"
    pattern = re.escape(start_tag) + r".*?" + re.escape(end_tag)
    if re.search(pattern, existing, flags=re.DOTALL):
        if img_tag in existing:
            print("[INFO] README.md already embeds the Dugout Dispatch image.")
            return False
        updated = re.sub(pattern, section, existing, flags=re.DOTALL)
    else:
        anchor = "</div>"
        if anchor in existing:
            updated = existing.replace(anchor, f"{anchor}\n\n---\n\n{section}", 1)
        else:
            updated = f"{existing}\n\n---\n\n{section}\n"
    if updated != existing:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"[OK] Inserted Dugout Dispatch image tag into {readme_path}")
        return True
    print("[INFO] No changes needed in README.md")
    return False


def main():
    parser = argparse.ArgumentParser(description="MLB Birthday Almanac Dispatch Generator")
    parser.add_argument("--month", type=int, default=None, help="Month (1-12). Defaults to today.")
    parser.add_argument("--day", type=int, default=None, help="Day (1-31). Defaults to today.")
    parser.add_argument("--target-file", type=str, default="README.md", help="Path to README.md")
    parser.add_argument("--svg-out", type=str, default="dugout-dispatch.svg", help="Path to write the rendered SVG card")
    parser.add_argument("--svg-url", type=str, default=DUGOUT_SVG_URL, help="URL the README <img> tag should point at")
    parser.add_argument("--dry-run", action="store_true", help="Print output without updating file")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    month = args.month or now.month
    day = args.day or now.day
    current_year = now.year

    print(f"Fetching MLB birthday records for {month:02d}/{day:02d}...")
    try:
        html = fetch_birthday_html(month, day)
    except Exception as e:
        print(f"Failed to fetch data: {e}", file=sys.stderr)
        sys.exit(1)

    players = parse_players(html)
    print(f"Successfully parsed {len(players)} players.")

    dispatch_md = build_daily_ledger(players, month, day, current_year)
    model = build_dispatch_model(players, month, day, current_year)
    svg = render_dugout_svg(model)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(dispatch_md)
        print("----------------------\n")
        return

    with open(args.svg_out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[OK] Wrote {args.svg_out}")

    ensure_dugout_image(args.target_file, args.svg_url)

    # Write to GitHub Step Summary if available
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path and os.path.exists(os.path.dirname(summary_path)):
        try:
            with open(summary_path, "a", encoding="utf-8") as sf:
                sf.write(f"\n{dispatch_md}\n")
            print("Wrote dispatch to GITHUB_STEP_SUMMARY.")
        except Exception as e:
            print(f"Notice: could not write to GITHUB_STEP_SUMMARY: {e}")


if __name__ == "__main__":
    main()
