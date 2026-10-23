#!/usr/bin/env python3
"""Generate the profile dashboard SVGs (dark + light) from the GitHub GraphQL API.

Usage: GITHUB_TOKEN=... python3 scripts/dashboard.py [login]
Only public data is used; private repositories never appear by name.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

LOGIN = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GH_LOGIN", "WoodyWizard")
OUT = Path(__file__).resolve().parent.parent / "assets"
# Markup and build files skew the language bar, so they are left out.
SKIP_LANGS = {"HTML", "CSS", "Makefile", "CMake", "Meson", "Vim Script", "Dockerfile"}

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    createdAt
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      totalCount
      nodes {
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def fetch():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if "errors" in data:
        sys.exit(json.dumps(data["errors"], indent=2))
    return data["data"]["user"]


def streaks(days):
    """Return (current, longest) streak in days. Today without activity yet doesn't break it."""
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    current = 0
    tail = list(reversed(days))
    if tail and tail[0]["contributionCount"] == 0:
        tail = tail[1:]
    for d in tail:
        if d["contributionCount"] == 0:
            break
        current += 1
    return current, longest


def collect(user):
    cc = user["contributionsCollection"]
    weeks = cc["contributionCalendar"]["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    repos = user["repositories"]["nodes"]
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            if name in SKIP_LANGS:
                continue
            item = langs.setdefault(name, {"size": 0, "color": e["node"]["color"] or "#8b949e"})
            item["size"] += e["size"]
    total = sum(v["size"] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1]["size"])[:6]
    rest = 1 - sum(v["size"] for _, v in top) / total
    languages = [(n, v["color"], v["size"] / total) for n, v in top]
    if rest > 0.005:
        languages.append(("Other", "#6e7681", rest))
    current, longest = streaks(days)
    best = max(days, key=lambda d: d["contributionCount"]) if days else None
    return {
        "name": user["name"] or LOGIN,
        "since": user["createdAt"][:4],
        "followers": user["followers"]["totalCount"],
        "contrib": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "reviews": cc["totalPullRequestReviewContributions"],
        "issues": cc["totalIssueContributions"],
        "private": cc["restrictedContributionsCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "forks": sum(r["forkCount"] for r in repos),
        "current": current,
        "longest": longest,
        "best": best,
        "weeks": weeks,
        "languages": languages,
        "active_days": sum(1 for d in days if d["contributionCount"] > 0),
    }


THEMES = {
    "dark": {
        "bg1": "#0e1a14", "bg2": "#13261c", "card": "#16291f", "stroke": "#24402f",
        "text": "#f3efe2", "muted": "#9fb3a5", "accent": "#f4d35e", "accent2": "#7bd389",
        "petal": "#f8f5ec", "petal_stroke": "none",
        "heat": ["#1b3125", "#2e5e3e", "#3f8a55", "#5fbf72", "#a6eb8f"],
    },
    "light": {
        "bg1": "#fbf8ef", "bg2": "#f1f6ec", "card": "#ffffff", "stroke": "#dfe7d8",
        "text": "#1d2a21", "muted": "#5d6f62", "accent": "#d9a400", "accent2": "#2f8a4c",
        "petal": "#ffffff", "petal_stroke": "#e3d9b8",
        "heat": ["#e9efe4", "#bfe3b4", "#7cc68a", "#3f9b5a", "#1f6b3a"],
    },
}
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

W, H = 860, 470
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"


def chamomile(cx, cy, r, t, spin=True):
    """A small chamomile flower: white petals around a yellow center."""
    petals = "".join(
        f'<ellipse cx="0" cy="{-r * 0.62:.1f}" rx="{r * 0.22:.1f}" ry="{r * 0.42:.1f}" '
        f'transform="rotate({a})" fill="{t["petal"]}" stroke="{t["petal_stroke"]}"/>'
        for a in range(0, 360, 30)
    )
    cls = ' class="spin"' if spin else ""
    return (
        f'<g transform="translate({cx},{cy})"><g{cls}>{petals}'
        f'<circle r="{r * 0.3:.1f}" fill="{t["accent"]}"/></g></g>'
    )


def tile(x, y, w, h, label, value, sub, color, t, delay):
    return f"""
  <g class="rise" style="animation-delay:{delay}s">
    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{t['card']}" stroke="{t['stroke']}"/>
    <rect x="{x}" y="{y + 18}" width="4" height="{h - 36}" rx="2" fill="{color}"/>
    <text x="{x + 20}" y="{y + 28}" class="label">{escape(label)}</text>
    <text x="{x + 20}" y="{y + 64}" class="big" fill="{color}">{escape(str(value))}</text>
    <text x="{x + 20}" y="{y + 86}" class="small">{escape(sub)}</text>
  </g>"""


def render(s, theme):
    t = THEMES[theme]
    today = dt.date.today()
    parts = [f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
  aria-label="{escape(s['name'])} GitHub dashboard">
  <title>{escape(s['name'])} · GitHub dashboard</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{t['bg1']}"/><stop offset="1" stop-color="{t['bg2']}"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: {FONT}; fill: {t['text']}; }}
    .title {{ font-size: 22px; font-weight: 700; }}
    .label {{ font-size: 12px; fill: {t['muted']}; letter-spacing: .08em; text-transform: uppercase; font-weight: 600; }}
    .big {{ font-family: {MONO}; font-size: 30px; font-weight: 700; }}
    .small {{ font-size: 12px; fill: {t['muted']}; }}
    .mono {{ font-family: {MONO}; font-size: 13px; fill: {t['muted']}; }}
    .rise {{ opacity: 0; animation: rise .7s ease-out forwards; }}
    .cell {{ opacity: 0; animation: pop .4s ease-out forwards; }}
    .grow {{ transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow 1.2s cubic-bezier(.2,.8,.2,1) .4s forwards; }}
    .spin {{ animation: spin 18s linear infinite; }}
    .blink {{ animation: blink 1s steps(1) infinite; }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
    @keyframes pop {{ to {{ opacity: 1; }} }}
    @keyframes grow {{ to {{ transform: scaleX(1); }} }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes blink {{ 50% {{ opacity: 0; }} }}
  </style>
  <rect width="{W}" height="{H}" rx="20" fill="url(#bg)" stroke="{t['stroke']}"/>
  {chamomile(812, 44, 26, t)}
  {chamomile(780, 74, 13, t)}
  <text x="30" y="48" class="title">~/{escape(LOGIN)} <tspan fill="{t['accent2']}">$</tspan> stats<tspan class="blink" fill="{t['accent']}">▌</tspan></text>
  <text x="30" y="72" class="mono">on GitHub since {s['since']} · {s['followers']} followers · updated {today:%Y-%m-%d}</text>
"""]

    # Stat tiles
    tiles = [
        ("Contributions", s["contrib"], "in the last year", t["accent2"]),
        ("Current streak", f"{s['current']}d", f"best: {s['longest']} days", t["accent"]),
        ("Commits", s["commits"], f"{s['prs']} pull requests · {s['reviews']} reviews", t["accent2"]),
        ("Stars earned", f"★ {s['stars']}", f"{s['repos']} public repos · {s['forks']} forks", t["accent"]),
    ]
    tw, gap = 190, 13
    for i, (label, value, sub, color) in enumerate(tiles):
        parts.append(tile(30 + i * (tw + gap), 92, tw, 100, label, value, sub, color, t, 0.1 + i * 0.12))

    # Language bar (right block, under the tiles row is the heatmap; languages sit on the bottom row)
    # Heatmap: last 53 weeks
    hx, hy, cell, cg = 30, 236, 11, 3
    parts.append(f'<g class="rise" style="animation-delay:.5s"><rect x="18" y="208" width="{W - 36}" height="140" rx="14" fill="{t["card"]}" stroke="{t["stroke"]}"/>')
    parts.append(f'<text x="32" y="230" class="label">Activity · last 12 months</text>')
    best = s["best"]
    if best and best["contributionCount"]:
        parts.append(
            f'<text x="{W - 32}" y="230" class="small" text-anchor="end">{s["active_days"]} active days · '
            f'busiest: {best["contributionCount"]} on {best["date"]}</text>'
        )
    parts.append("</g>")
    weeks = s["weeks"][-58:]
    hx = (W - (len(weeks) * (cell + cg) - cg)) / 2
    month_seen = None
    for wi, w in enumerate(weeks):
        x = hx + wi * (cell + cg)
        first = w["contributionDays"][0]["date"]
        month = first[5:7]
        if month != month_seen and int(first[8:10]) <= 7:
            name = dt.date.fromisoformat(first).strftime("%b")
            parts.append(f'<text x="{x:.1f}" y="{hy + 10}" class="small" style="font-size:10px">{name}</text>')
            month_seen = month
        for d in w["contributionDays"]:
            wd = dt.date.fromisoformat(d["date"]).isoweekday() % 7  # Sunday = 0
            y = hy + 18 + wd * (cell + cg)
            lvl = LEVELS.get(d["contributionLevel"], 0)
            delay = 0.6 + wi * 0.018
            parts.append(
                f'<rect class="cell" style="animation-delay:{delay:.2f}s" x="{x:.1f}" y="{y}" width="{cell}" height="{cell}" '
                f'rx="2.5" fill="{t["heat"][lvl]}"><title>{d["date"]}: {d["contributionCount"]}</title></rect>'
            )

    # Bottom left: breakdown
    by = 364
    parts.append(f'<g class="rise" style="animation-delay:.8s"><rect x="18" y="{by}" width="420" height="88" rx="14" fill="{t["card"]}" stroke="{t["stroke"]}"/>')
    parts.append(f'<text x="34" y="{by + 26}" class="label">Last 12 months in numbers</text>')
    rows = [
        ("commits", s["commits"]), ("pull requests", s["prs"]),
        ("issues", s["issues"]), ("private work", s["private"]),
    ]
    for i, (k, v) in enumerate(rows):
        x = 34 + i * 100
        parts.append(f'<text x="{x}" y="{by + 58}" class="big" style="font-size:22px" fill="{t["accent2"] if i % 2 == 0 else t["accent"]}">{v}</text>')
        parts.append(f'<text x="{x}" y="{by + 76}" class="small">{k}</text>')
    parts.append("</g>")

    # Bottom right: languages
    lx, lw = 454, W - 454 - 18
    parts.append(f'<g class="rise" style="animation-delay:.95s"><rect x="{lx}" y="{by}" width="{lw}" height="88" rx="14" fill="{t["card"]}" stroke="{t["stroke"]}"/>')
    parts.append(f'<text x="{lx + 16}" y="{by + 26}" class="label">Languages</text>')
    bx, bw = lx + 16, lw - 32
    parts.append(f'<clipPath id="lc"><rect x="{bx}" y="{by + 36}" width="{bw}" height="10" rx="5"/></clipPath><g clip-path="url(#lc)"><g class="grow">')
    cur = bx
    for name, color, share in s["languages"]:
        seg = bw * share
        parts.append(f'<rect x="{cur:.1f}" y="{by + 36}" width="{seg + 0.5:.1f}" height="10" fill="{color}"/>')
        cur += seg
    parts.append("</g></g>")
    for i, (name, color, share) in enumerate(s["languages"][:6]):
        col, row = i % 3, i // 3
        x, y = bx + col * (bw / 3), by + 64 + row * 17
        parts.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{x + 13}" y="{y}" class="small">{escape(name)} <tspan class="mono" style="font-size:11px">{share * 100:.1f}%</tspan></text>')
    parts.append("</g>")

    parts.append("</svg>\n")
    return "\n".join(parts)


def main():
    stats = collect(fetch())
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (OUT / f"dashboard-{theme}.svg").write_text(render(stats, theme), encoding="utf-8")
    print(f"dashboard updated: {stats['contrib']} contributions, streak {stats['current']}d, ★{stats['stars']}")


if __name__ == "__main__":
    main()
