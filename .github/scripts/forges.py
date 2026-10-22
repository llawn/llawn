"""Build forges.svg: a combined summary of my GitHub, Codeberg and GitLab accounts.

Tokens are optional and read from the environment:
  GITHUB_TOKEN   raises the GitHub rate limit
  CODEBERG_TOKEN only needed to list starred repositories
  GITLAB_TOKEN   used only for the GitLab follower count (also pushes the profile README)
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

GITHUB_USER = "llawn"
CODEBERG_USER = "llawn"
GITLAB_USER = "llawn06"
# Profile README repos mirror each other and are not projects.
PROFILE_REPOS = {GITHUB_USER, ".profile", GITLAB_USER}
OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "forges.svg"

# Subset of GitHub linguist colors; anything else falls back to grey.
LANG_COLORS = {
    "Astro": "#ff5a03", "C": "#555555", "C++": "#f34b7d", "CSS": "#663399",
    "Dart": "#00b4ab", "Dockerfile": "#384d54", "Fish": "#4aae47", "Go": "#00add8",
    "HTML": "#e34c26", "JavaScript": "#f1e05a", "Lua": "#000080", "Makefile": "#427819",
    "MATLAB": "#e16737", "Nix": "#7e7eff", "Python": "#3572a5", "R": "#198ce7",
    "Rust": "#dea584", "Scheme": "#1e4aec", "Shell": "#89e051", "TeX": "#3d6117",
    "Tree-sitter Query": "#8ea64c", "TypeScript": "#3178c6", "Typst": "#239dad",
    "Vim Script": "#199f4b", "Zig": "#ec915c",
}
OTHER_COLOR = "#8b949e"
ACTIVITY_DAYS = 100
STARRED_PER_FORGE = 3


def get(url, token=None, auth="token", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "forges-card", "Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"{auth} {token}" if auth else token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def try_get(url, token=None, auth="token", default=None, body=None):
    try:
        return get(url, token, auth, body)
    except Exception as e:  # one broken forge should not break the card
        print(f"warning: {url}: {e}", file=sys.stderr)
        return default


def github():
    tok = os.environ.get("GITHUB_TOKEN")
    api = "https://api.github.com"
    user = try_get(f"{api}/users/{GITHUB_USER}", tok, "Bearer", {})
    repos = [r for r in try_get(f"{api}/users/{GITHUB_USER}/repos?per_page=100", tok, "Bearer", []) if not r["fork"] and r["name"] not in PROFILE_REPOS]
    # The contribution calendar is only exposed through GraphQL, which needs a token.
    activity = {}
    if tok:
        query = f'{{user(login:"{GITHUB_USER}"){{contributionsCollection{{contributionCalendar{{weeks{{contributionDays{{date contributionCount}}}}}}}}}}}}'
        res = try_get(f"{api}/graphql", tok, "Bearer", {}, {"query": query})
        weeks = (((res.get("data") or {}).get("user") or {}).get("contributionsCollection") or {}).get("contributionCalendar", {}).get("weeks", [])
        activity = {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}
    starred = try_get(f"{api}/users/{GITHUB_USER}/starred?per_page=100", tok, "Bearer", [])
    return {
        "name": "GitHub",
        "url": f"https://github.com/{GITHUB_USER}",
        "followers": user.get("followers"),
        "activity": activity,
        "starred": [
            {"name": r["full_name"], "stars": r["stargazers_count"], "language": r["language"]}
            for r in starred
        ],
        "repos": [
            {
                "name": r["name"],
                "stars": r["stargazers_count"],
                "updated": r["pushed_at"],
                "languages": try_get(r["languages_url"], tok, "Bearer", {}),
            }
            for r in repos
        ],
    }


def codeberg():
    tok = os.environ.get("CODEBERG_TOKEN")
    api = "https://codeberg.org/api/v1"
    user = try_get(f"{api}/users/{CODEBERG_USER}", tok, default={})
    repos = [r for r in try_get(f"{api}/users/{CODEBERG_USER}/repos?limit=50", tok, default=[]) if not r["fork"] and r["name"] not in PROFILE_REPOS]
    activity = {}
    for h in try_get(f"{api}/users/{CODEBERG_USER}/heatmap", tok, default=[]):
        day = datetime.fromtimestamp(h["timestamp"], timezone.utc).date().isoformat()
        activity[day] = activity.get(day, 0) + h["contributions"]
    # Gitea only lists stars to an authenticated client.
    starred = try_get(f"{api}/users/{CODEBERG_USER}/starred?limit=50", tok, default=[]) if tok else []
    return {
        "name": "Codeberg",
        "url": f"https://codeberg.org/{CODEBERG_USER}",
        "followers": user.get("followers_count"),
        "activity": activity,
        "starred": [{"name": r["full_name"], "stars": r["stars_count"], "language": r["language"]} for r in starred],
        "repos": [
            {
                "name": r["name"],
                "stars": r["stars_count"],
                "updated": r["updated_at"],
                "languages": try_get(f"{api}/repos/{r['full_name']}/languages", tok, default={}),
            }
            for r in repos
        ],
    }


def gitlab():
    tok = os.environ.get("GITLAB_TOKEN")
    api = "https://gitlab.com/api/v4"
    # Public endpoints are queried anonymously; the token (which may only be allowed
    # to push) is used for the follower count alone.
    users = try_get(f"{api}/users?username={GITLAB_USER}", default=[])
    if not users:
        return {"name": "GitLab", "url": f"https://gitlab.com/{GITLAB_USER}", "followers": None, "repos": [], "activity": {}, "starred": []}
    uid = users[0]["id"]
    user = try_get(f"{api}/users/{uid}", tok, "Bearer", {}) if tok else {}
    projects = try_get(f"{api}/users/{uid}/projects?per_page=100", default=[])
    repos = []
    for p in projects:
        if p.get("forked_from_project") or p["path"] in PROFILE_REPOS:
            continue
        # GitLab reports languages as percentages; weight them by a nominal size so
        # projects count roughly like one average repository.
        pct = try_get(f"{api}/projects/{p['id']}/languages", default={})
        repos.append({
            "name": p["path"],
            "stars": p["star_count"],
            "updated": p["last_activity_at"],
            "languages": {k: v * 1000 for k, v in pct.items()},
        })
    return {
        "name": "GitLab",
        "url": f"https://gitlab.com/{GITLAB_USER}",
        "followers": user.get("followers"),
        # Not part of the REST API, but public and used by the profile page itself.
        "activity": try_get(f"https://gitlab.com/users/{GITLAB_USER}/calendar.json", default={}),
        # No language is exposed here.
        "starred": [
            {"name": p["path_with_namespace"], "stars": p["star_count"], "language": None}
            for p in try_get(f"{api}/users/{uid}/starred_projects?per_page=100", default=[])
        ],
        "repos": repos,
    }


def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def short(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def streaks(counts):
    """Current and longest runs of active days; today does not break the current run yet."""
    longest = run = 0
    for n in counts:
        run = run + 1 if n else 0
        longest = max(longest, run)
    tail = counts if counts[-1] else counts[:-1]
    current = 0
    for n in reversed(tail):
        if not n:
            break
        current += 1
    return current, longest


def build_svg(forges):
    # Mirrored repos (same name on several forges) count once: keep the freshest copy.
    unique = {}
    for f in forges:
        for r in f["repos"]:
            r = {**r, "forge": f["name"]}
            key = r["name"].lower()
            if key not in unique or parse_date(r["updated"]) > parse_date(unique[key]["updated"]):
                unique[key] = r

    langs = {}
    for r in unique.values():
        for k, v in r["languages"].items():
            langs[k] = langs.get(k, 0) + v
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:8]
    rest = total - sum(v for _, v in top)
    if rest > 0:
        top.append(("Other", rest))

    recent = sorted(unique.values(), key=lambda r: parse_date(r["updated"]), reverse=True)[:5]

    W, pad = 480, 16
    out = []
    y = 28
    out.append(f'<text x="{pad}" y="{y}" class="title">Across forges</text>')
    out.append(
        f'<text x="{W - pad}" y="{y}" class="muted" text-anchor="end">'
        f'{len(unique)} projects · {sum(r["stars"] for r in unique.values())} stars</text>'
    )

    # One column per forge.
    y += 22
    col = (W - 2 * pad) / len(forges)
    for i, f in enumerate(forges):
        x = pad + i * col
        stars = sum(r["stars"] for r in f["repos"])
        followers = "–" if f["followers"] is None else f["followers"]
        out.append(f'<a href="{escape(f["url"])}"><text x="{x}" y="{y + 14}" class="forge">{f["name"]}</text></a>')
        out.append(f'<text x="{x}" y="{y + 34}" class="stat">{len(f["repos"])} repos · {stars} ★</text>')
        out.append(f'<text x="{x}" y="{y + 52}" class="muted">{followers} followers</text>')
    y += 76

    # Language bar and legend.
    out.append(f'<text x="{pad}" y="{y}" class="section">Languages</text>')
    y += 10
    x, bar_w = pad, W - 2 * pad
    out.append(f'<clipPath id="bar"><rect x="{pad}" y="{y}" width="{bar_w}" height="8" rx="4"/></clipPath><g clip-path="url(#bar)">')
    for name, v in top:
        w = bar_w * v / total
        out.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="8" fill="{LANG_COLORS.get(name, OTHER_COLOR)}"/>')
        x += w
    out.append("</g>")
    y += 26
    for i, (name, v) in enumerate(top):
        lx = pad + (i % 3) * (bar_w / 3)
        ly = y + (i // 3) * 20
        out.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{LANG_COLORS.get(name, OTHER_COLOR)}"/>')
        out.append(f'<text x="{lx + 15}" y="{ly}" class="stat">{escape(name)} <tspan class="muted">{100 * v / total:.1f}%</tspan></text>')
    y += ((len(top) + 2) // 3) * 20 + 14

    # Contributions over the last ACTIVITY_DAYS, summed across forges, GitHub-style (weeks start on Sunday),
    # with a per-forge breakdown and streaks beside the calendar.
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(ACTIVITY_DAYS - 1, -1, -1)]
    per_forge = {f["name"]: [f["activity"].get(d.isoformat(), 0) for d in days] for f in forges}
    counts = [sum(c[i] for c in per_forge.values()) for i in range(len(days))]
    peak = max(counts) or 1
    out.append(f'<text x="{pad}" y="{y}" class="section">Activity</text>')
    out.append(f'<text x="{W - pad}" y="{y}" class="muted" text-anchor="end">last {ACTIVITY_DAYS} days</text>')
    y += 12
    step, cell = 17, 14
    lead = (days[0].weekday() + 1) % 7
    for i, (d, n) in enumerate(zip(days, counts)):
        level = 0 if n == 0 else min(4, 1 + 4 * (n - 1) // peak)
        k = i + lead
        detail = ", ".join(f"{name} {c[i]}" for name, c in per_forge.items() if c[i])
        tip = f"{d.isoformat()}: {n}" + (f" ({detail})" if detail else "")
        out.append(f'<rect x="{pad + (k // 7) * step}" y="{y + (k % 7) * step}" width="{cell}" height="{cell}" rx="2" class="l{level}"><title>{tip}</title></rect>')

    sx = pad + ((lead + len(days) - 1) // 7 + 1) * step + 16
    rows = []
    for name, c in per_forge.items():
        rows.append((name, f"{sum(c)} · {sum(1 for n in c if n)}d", f"f-{name.lower()}"))
    current, longest = streaks(counts)
    best = max(range(len(days)), key=lambda i: counts[i])
    rows += [
        ("Total", str(sum(counts)), None),
        ("Active days", f"{sum(1 for n in counts if n)} / {ACTIVITY_DAYS}", None),
        ("Streak", f"{current}d (best {longest}d)", None),
        ("Best day", f"{days[best].strftime('%b %d')} · {counts[best]}" if counts[best] else "–", None),
    ]
    for i, (label, value, dot) in enumerate(rows):
        ry = y + i * step + 11
        tx = sx
        if dot:
            out.append(f'<circle cx="{sx + 4}" cy="{ry - 4}" r="4" class="{dot}"/>')
            tx += 13
        out.append(f'<text x="{tx}" y="{ry}" class="{"stat" if dot else "muted"}">{label}</text>')
        out.append(f'<text x="{W - pad}" y="{ry}" class="stat" text-anchor="end">{value}</text>')
    y += 7 * step + 22

    # Most recently updated projects, wherever they live.
    out.append(f'<text x="{pad}" y="{y}" class="section">Recently active</text>')
    y += 22
    for r in recent:
        when = parse_date(r["updated"]).strftime("%Y-%m-%d")
        out.append(f'<text x="{pad}" y="{y}" class="stat">{escape(r["name"])}</text>')
        out.append(f'<text x="{W - pad}" y="{y}" class="muted" text-anchor="end">{r["forge"]} · {when}</text>')
        y += 20

    # Most-starred repositories I starred, per forge so a big forge does not crowd out the others.
    with_stars = [f for f in forges if f["starred"]]
    if with_stars:
        y += 10
        out.append(f'<text x="{pad}" y="{y}" class="section">Starred</text>')
        y += 4
        for f in with_stars:
            y += 20
            out.append(f'<text x="{pad}" y="{y}" class="muted">{f["name"]}</text>')
            y += 20
            for s in sorted(f["starred"], key=lambda s: s["stars"], reverse=True)[:STARRED_PER_FORGE]:
                meta = [f"★ {short(s['stars'])}"] + ([s["language"]] if s["language"] else [])
                name = s["name"] if len(s["name"]) <= 44 else s["name"][:43] + "…"
                out.append(f'<text x="{pad + 12}" y="{y}" class="stat">{escape(name)}</text>')
                out.append(f'<text x="{W - pad}" y="{y}" class="muted" text-anchor="end">{escape(" · ".join(meta))}</text>')
                y += 20
            y -= 20
        y += 20

    y += 4
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(f'<text x="{W - pad}" y="{y}" class="tiny" text-anchor="end">Updated {stamp}</text>')
    H = y + 12

    style = """
    text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; fill: #24292f; }
    .title { font-size: 16px; font-weight: 600; }
    .section { font-size: 14px; font-weight: 600; }
    .forge { font-size: 14px; font-weight: 600; fill: #0969da; }
    .stat { font-size: 12px; }
    .muted { font-size: 12px; fill: #57606a; }
    .tiny { font-size: 10px; fill: #8c959f; }
    .f-github { fill: #24292f; } .f-codeberg { fill: #2185d0; } .f-gitlab { fill: #fc6d26; }
    .l0 { fill: #ebedf0; } .l1 { fill: #9be9a8; } .l2 { fill: #40c463; } .l3 { fill: #30a14e; } .l4 { fill: #216e39; }
    @media (prefers-color-scheme: dark) {
      text { fill: #c9d1d9; }
      .forge { fill: #58a6ff; }
      .muted { fill: #8b949e; }
      .tiny { fill: #6e7681; }
      .f-github { fill: #f0f6fc; }
      .l0 { fill: #161b22; } .l1 { fill: #0e4429; } .l2 { fill: #006d32; } .l3 { fill: #26a641; } .l4 { fill: #39d353; }
    }
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f"<style>{style}</style>" + "".join(out) + "</svg>\n"
    )


def main():
    forges = [github(), codeberg(), gitlab()]
    with open(OUTPUT, "w") as fh:
        fh.write(build_svg(forges))
    for f in forges:
        print(f"{f['name']}: {len(f['repos'])} repos, followers={f['followers']}, active days={len(f['activity'])}, starred={len(f['starred'])}")


if __name__ == "__main__":
    main()
