#!/usr/bin/env python3
"""
MLB Birthday Almanac Generator
Fetches MLB players born on the current (or specified) calendar day, computes
sabermetric superlatives, and injects a clean markdown ledger into README.md.
Zero third-party dependencies (standard library only).
"""

import argparse
import datetime
import os
import re
import sys
import urllib.request
from typing import Dict, List, Optional, Any


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


def build_daily_ledger(players: List[Dict[str, Any]], month: int, day: int, current_year: int) -> str:
    month_name = datetime.date(2024, month, day).strftime("%B")
    date_str = f"{month_name} {day}"

    if not players:
        return f"### Daily Dugout Dispatch: {date_str}\n\n*No MLB player birth records indexed for this date.*\n"

    # 1. Career Value Ace (WAR leader)
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
        if p["year_min"] == p["year_max"]:
            return f"{p['year_min']}"
        if p["year_max"] >= (current_year - 1):
            return f"{p['year_min']}–Pres"
        return f"{p['year_min']}–{p['year_max']}"

    def format_player_link(p: Dict[str, Any]) -> str:
        name_str = p["name"]
        if p["is_hof"]:
            name_str += " (HOF)"
        return f"[{name_str}]({p['bref_url']})"

    def format_war_metrics(p: Dict[str, Any]) -> str:
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

    def format_polymath_metrics(p: Dict[str, Any]) -> str:
        team_count = len(p["franchises"])
        teams_str = ", ".join(p["franchises"][:6]) + ("..." if len(p["franchises"]) > 6 else "")
        return f"{team_count} Clubs ({teams_str}) • {p['war']:.1f} bWAR • {p['experience']} Yrs — a true Immaculate Grid cheat code"

    def format_vintage_metrics(p: Dict[str, Any]) -> str:
        age_notes = f"Born {p['birth_year']}"
        parts = [age_notes, f"{p['experience']} Seasons", f"{p['war']:.1f} bWAR"]
        if p["is_pitcher"] and p["g_p"] > 0:
            parts.append(f"{p['g_p']} G ({p['gs']} GS)")
        elif p["hits"] > 0:
            parts.append(f"{p['hits']:,} H")
        return " • ".join(parts)

    def format_franchises(p: Dict[str, Any], max_display: int = 5) -> str:
        if not p["franchises"]:
            return "—"
        if len(p["franchises"]) <= max_display:
            return ", ".join(p["franchises"])
        return ", ".join(p["franchises"][:max_display]) + f" (+{len(p['franchises']) - max_display})"

    # Build markdown table
    lines = [
        f"### Daily Dugout Dispatch: {date_str}",
        "",
        "| Category | Player | Active Span | Franchise(s) | Key Sabermetrics |",
        "| :--- | :--- | :--- | :--- | :--- |",
        f"| **Career Value Ace** | {format_player_link(war_leader)} | {format_span(war_leader)} | {format_franchises(war_leader)} | {format_war_metrics(war_leader)} |",
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
    
    # Active Player roster note if present
    if active_players:
        def format_active_organization(p: Dict[str, Any]) -> str:
            """Return an active player's MLB organization, or FA when unsigned."""
            organization = p["franchises"][-1] if p["franchises"] else ""
            return "FA" if not organization or organization.upper() == "TBD" else organization

        active_names = [f"{format_player_link(ap)} ({format_active_organization(ap)})" for ap in active_players]
        lines.append(f"*Active cohort on MLB active rosters today ({len(active_players)}):* {', '.join(active_names)}")
        lines.append("")

    lines.append(f"*Historical index contains {len(players)} total Major League Baseball players born on {date_str}.*")
    lines.append("")

    return "\n".join(lines)


def update_readme(target_file: str, new_content: str) -> bool:
    start_tag = "<!-- MLB_BIRTHDAY_START -->"
    end_tag = "<!-- MLB_BIRTHDAY_END -->"

    if not os.path.exists(target_file):
        print(f"Error: Target file {target_file} not found.", file=sys.stderr)
        return False

    with open(target_file, "r", encoding="utf-8") as f:
        existing = f.read()

    replacement_block = f"{start_tag}\n{new_content.strip()}\n{end_tag}"

    if start_tag in existing and end_tag in existing:
        pattern = re.compile(rf"{re.escape(start_tag)}.*?{re.escape(end_tag)}", re.DOTALL)
        updated = pattern.sub(replacement_block, existing)
    else:
        # If tags are not present, append after professional overview
        anchor = "### Professional Overview"
        if anchor in existing:
            updated = existing.replace(anchor, f"{replacement_block}\n\n---\n\n{anchor}")
        else:
            updated = f"{existing}\n\n---\n\n{replacement_block}\n"

    if updated != existing:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"Successfully updated {target_file}")
        return True
    else:
        print(f"No changes required for {target_file}")
        return False


def main():
    parser = argparse.ArgumentParser(description="MLB Birthday Almanac Dispatch Generator")
    parser.add_argument("--month", type=int, default=None, help="Month (1-12). Defaults to today.")
    parser.add_argument("--day", type=int, default=None, help="Day (1-31). Defaults to today.")
    parser.add_argument("--target-file", type=str, default="README.md", help="Path to README.md")
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

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(dispatch_md)
        print("----------------------\n")
    else:
        update_readme(args.target_file, dispatch_md)

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
