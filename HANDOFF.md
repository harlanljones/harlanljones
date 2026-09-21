# Handoff — GitHub Profile Cards

State as of Sep 21, 2026. Repo: `~/harlanljones` (all pushed to main unless noted).

## Projects section (merged card — `render_project_index.py`, drawn by `repo-cards.yml`)

Replaced the old Featured Projects pill wall. One repo per section, best section wins.
Current lineup (recomputed each Sunday run):

- **Top 5 · by gWAR** — dotfiles, urban-signal, dotfiles-showcase, baseball-dashboard, omarchy-agents
- **Fresh off the bench** (newest created, gWAR > 0) — sleeper-zone-desktop, jev-roster-shapes, draft, proof, rosetta
- **Live in production** (has homepage) — bayes-horizon, arbkit, film-lab, ferrite-db
- **The long haul** (oldest created, pushed in 90d) — saberkit, scheme-db, herdr-outpost

Rules baked in: no duplicates across sections; profile repo `harlanljones/harlanljones` excluded from all rankings; Fresh skips negative-gWAR repos; summaries/badges come from `scripts/data/featured_projects.json` (projects-sync still updates the store weekly but no longer renders the card).

## Stats on the page (all defined in Glossary card)

- wRP — skill reps from mirror diffs (collector)
- gWAR — repo composite vs 20th-pct replacement (repo-cards)
- Lang+ / Pace+ — 100-neutral splits (commit-rhythm / activity / grid)
- wDC — weighted Deployments Created, Cloudflare Pages+Workers deploys, 4-week recency weights (collector → pipeline card)
- ERA — Actions Env Reliability Average = 9 × regressed failure rate, lower better (collector → pipeline card)

## Automation

- Nightly **profile-collector** (GCP Cloud Run, `collector/`, schedule 03:15 PT) mirrors all owned repos, mines full diffs, renders skills / commit-rhythm / pipeline / glossary, pushes store to main + SVGs to `profile-cards`. Secrets: gh-read-token, gh-write-token, cloudflare-token, cloudflare-account (Secret Manager; setup.sh idempotent).
- GitHub Actions: activity-cards (daily), mlb-birthdays (daily), weekly-highlights (Fri), projects-sync (Sat, store only), repo-cards (Sun — leaderboard, spotlight, grid, projects).
- Header / overview are hand-rendered: run `python3 scripts/render_header_svg.py` / `render_overview_svg.py` and push outputs to `profile-cards` (they were stale on the live page as of this handoff — new wording "Software Engineer @ PrimeIQ.ai" not yet pushed).

## Commit-filter policy (collector)

Included: my identities + dev agents (Claude, Cursor, Copilot) + CI bots that fix code. Excluded: pure automations — `profile-collector`, `github-actions[bot]`, dependabot/renovate, `[skip ci]`/snapshot messages. Logic: `AUTOMATION_*` in `scripts/skill_signals.py`.

## Open / next

1. **Language Activity chart (commit-rhythm card)**: currently sorted by commit share. Change to sort by **Lang+** and show **top 5 by Lang+** (in `render_activity_svg.py` → `_language_timeseries_chart` caller; sort the `series`/`plus` dict by `plus[name]` desc instead of season share).
2. Header/overview SVGs need regenerating + push to `profile-cards` (see above).
3. Verify after next runs: leaderboard shows full names (truncation fixed Sep 21), pipeline card tiles show real wDC (~11) and ERA (~1.84, green).
4. Known intentional: activity card commit counts (GraphQL calendar) differ from rhythm card (mirror-mined) — different sources, not a bug.

## Verification notes

No test suite. Ad-hoc checks used: `bash -n`, `python -m py_compile`, render + `cairosvg` → PNG → vision review. gitleaks runs on pre-push. CI in dotfiles repo (separate) validates INDEX.
