#!/usr/bin/env python3
"""
Renders the Glossary card: one place that defines every homegrown stat on
the profile (wRP, gWAR, Lang+, Pace+), so the cards themselves can stay terse.

Static text; the weekly skills workflow re-renders it alongside skills.svg so
it never drifts far from the code. Keep entries in sync with sabermetrics.py,
skill_signals.py, and render_repo_cards.py.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_AMBER,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    card_shell,
    esc,
    wrap_by_width,
    write_theme_pair,
)

# (term, expansion, formula, plain-language explanation)
ENTRIES = [
    ("wRP", "weighted Reps Practiced",
     "Σ commits √min(400, lines credited to the skill) · 4-week weights 1 / .6 / .36 / .22",
     "Reads each week's actual diffs, not commit messages, across every repo I own: my commits, the dev agents' (Claude, Cursor, Copilot) and code-fixing CI bots'; pure automations — snapshot pushes, dependency bots — don't count. A file that is the skill (Dockerfile, workflow YAML, "
     "test file) credits all its changed lines; a changed line that uses it (import torch, async def, CREATE TABLE) "
     "credits 4 lines of context. Deletions count half; lockfiles, vendored and generated files are ignored. "
     "The square root rewards steady, focused reps over one giant dump. Bubbles show the percentile of that "
     "4-week wRP among every skill's 4-week wRP over the last 26 weeks, a league made of my own skill-weeks: "
     "50 is a median skill-week, 99 is among my most-practiced."),
    ("gWAR", "Git Wins Above Replacement",
     "ln(1+commits 90d) + 1.25·ln(1+stars) + 0.75·ln(1+forks) + freshness − replacement",
     "Runs created by a repo: recent activity and adoption, log-damped so one viral repo or one sprint can't own "
     "the scale, plus up to 1 for a push in the last 90 days. Replacement level is the 20th-percentile repo in "
     "my public index, so a forgettable repo sits near 0 and can dip negative. Not Baseball-Reference's bWAR."),
    ("Lang+", "language usage, 100-neutral split",
     "100 × (30-day share, regressed) ÷ 12-month share",
     "Like OPS+: 100 is my normal usage of a language, 130 means 30% more of my commits touched it this month "
     "than over the year. Languages come from the extensions of the files each commit changed, across every "
     "repo and branch, so a commit counts once for each language it touched. The 30-day share is regressed "
     "toward the season share with 25 phantom commits, so a language needs real volume before it moves far from 100."),
    ("wDC", "weighted Deployments Created",
     "Σ weeks-of-last-4 (deployments that week) · weights 1 / .6 / .36 / .22",
     "Every deployment I created in the last four weeks: Cloudflare Pages deploys plus Workers "
      "last-deployed timestamps. Recency-weighted, so shipping this week counts about five times as "
      "much as shipping four weeks ago. On the Season Stat Line card."),
    ("aERA", "adjusted Actions ERA",
     "9 × (failed runs, regressed) ÷ total runs · lower is better",
     "Borrowed from pitching: earned runs per 9 innings, here failed GitHub Actions runs per 9 runs "
     "across my public repos over the last 28 days. League average is about 4.50; green means the "
     "pipelines mostly stay up. Small samples are regressed toward 4.50 with 9 phantom league-average "
     "runs. The lowercase-a prefix keeps it clear of the pitching ERA on the Dugout Dispatch card."),
    ("Pace+", "commit pace, 100-neutral split",
     "100 × (recent daily rate, regressed) ÷ baseline daily rate",
     "Recent pace against the usual pace, regressed with 7 days at the baseline rate. Activity: the last 30 days "
     "of contributions vs the year. Repo cards and the Immaculate Grid: a repo's last 30 days of commits vs "
     "its own 90-day rate."),
    ("FIX−", "corrective load, 100-neutral",
     "100 × 28-day fix share (regressed) ÷ season fix share",
     "Share of commits fixing rather than building: subjects matching fix, hotfix, revert, or bugfix across "
     "every owned repo and branch. 100 is my usual load, 70 means a third fewer fixes than usual. On the "
     "Season Stat Line card."),
    ("SHIP+", "share of active repos shipping",
     "repos with a release in 90 days ÷ active repos",
     "What share of repos I actually touched shipped a release this quarter. Higher is better. On the "
     "Season Stat Line card."),
    ("dOUT−", "sidelined repos",
     "repos whose latest default-branch check failed",
     "The injured list: a plain count, lower is better. On the Season Stat Line card."),
    ("wMRG+", "recency-weighted merge rate",
     "merged ÷ decided PRs, weeks weighted 1/.6/.36/.22",
     "Share of closed pull requests that merged over 90 days, this week's outcomes counting most. Higher is "
     "better. On the Season Stat Line card."),
    ("+/−", "polarity suffixes",
     "100 = my normal baseline",
     "A trailing + means higher is more-or-better (Lang+, Pace+, SHIP+); a trailing − means lower is better "
     "(FIX−, RUST−). On a 100-neutral split, 100 is always my normal rate and distance from 100 is the story, "
     "in whichever direction the suffix points."),
    ("a w g d n", "method and scope prefixes",
     "a regressed · w recency-weighted · g/d/n scoped",
     "a (adjusted): small samples are regressed toward the baseline with phantom league-average events, so a "
     "quiet stretch can't fake elite (aERA, aTURN−). w (weighted): weekly values decay 1, .6, .36, .22 "
     "newest-first, so this week counts about five times as much as four weeks ago (wDC, wMRG+, wROT+). g/d/n "
     "scope the count: git-native totals, the default branch, or nocturnal hours outside 9–5 PT."),
]


def render() -> str:
    max_w = CARD_WIDTH - PAD_X * 2
    term_w = 96
    text_x = PAD_X + term_w
    text_w = max_w - term_w
    cy = 6.0
    frags = []
    for i, (term, expansion, formula, body) in enumerate(ENTRIES):
        if i:
            frags.append(f'<line x1="{PAD_X}" y1="{cy - 8:.1f}" x2="{CARD_WIDTH - PAD_X}" y2="{cy - 8:.1f}" '
                         f'stroke="{BORDER}" stroke-width="1"/>')
        frags.append(
            f'<text x="{PAD_X}" y="{cy + 13:.1f}" font-size="15" font-weight="800" fill="{ACCENT_AMBER}" '
            f'font-family="{FONT_FAMILY}">{esc(term)}</text>'
            f'<text x="{text_x}" y="{cy + 13:.1f}" font-size="12.5" font-weight="700" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(expansion)}</text>'
        )
        cy += 20
        frags.append(
            f'<text x="{text_x}" y="{cy + 11:.1f}" font-size="11" fill="{TEXT}" '
            f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">{esc(formula)}</text>'
        )
        cy += 18
        for line in wrap_by_width(body, 11.5, text_w):
            frags.append(f'<text x="{text_x}" y="{cy + 11:.1f}" font-size="11.5" fill="{MUTED}" '
                         f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
            cy += 16
        cy += 18
    return card_shell("Glossary", "the homegrown stats on this page, and how they're computed",
                      "\n".join(frags), cy - 18, accent=ACCENT_AMBER)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="glossary.svg")
    args = parser.parse_args()
    for path in write_theme_pair(args.out, render()):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
