"""Build forges.svg: a combined summary of my GitHub, Codeberg and GitLab accounts.

Tokens are optional and read from the environment:
  GITHUB_TOKEN   raises the GitHub rate limit
  CODEBERG_TOKEN not required (public data only)
  GITLAB_TOKEN   used only for the GitLab follower count (also pushes the profile README)
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
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


def get(url, token=None, auth="token"):
    req = urllib.request.Request(url, headers={"User-Agent": "forges-card", "Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"{auth} {token}" if auth else token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def try_get(url, token=None, auth="token", default=None):
    try:
        return get(url, token, auth)
    except Exception as e:  # one broken forge should not break the card
        print(f"warning: {url}: {e}", file=sys.stderr)
        return default


def github():
    tok = os.environ.get("GITHUB_TOKEN")
    api = "https://api.github.com"
    user = try_get(f"{api}/users/{GITHUB_USER}", tok, "Bearer", {})
    repos = [r for r in try_get(f"{api}/users/{GITHUB_USER}/repos?per_page=100", tok, "Bearer", []) if not r["fork"] and r["name"] not in PROFILE_REPOS]
    return {
        "name": "GitHub",
        "url": f"https://github.com/{GITHUB_USER}",
        "followers": user.get("followers"),
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
    return {
        "name": "Codeberg",
        "url": f"https://codeberg.org/{CODEBERG_USER}",
        "followers": user.get("followers_count"),
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
        return {"name": "GitLab", "url": f"https://gitlab.com/{GITLAB_USER}", "followers": None, "repos": []}
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
        "repos": repos,
    }


def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


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

    # Most recently updated projects, wherever they live.
    out.append(f'<text x="{pad}" y="{y}" class="section">Recently active</text>')
    y += 22
    for r in recent:
        when = parse_date(r["updated"]).strftime("%Y-%m-%d")
        out.append(f'<text x="{pad}" y="{y}" class="stat">{escape(r["name"])}</text>')
        out.append(f'<text x="{W - pad}" y="{y}" class="muted" text-anchor="end">{r["forge"]} · {when}</text>')
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
    @media (prefers-color-scheme: dark) {
      text { fill: #c9d1d9; }
      .forge { fill: #58a6ff; }
      .muted { fill: #8b949e; }
      .tiny { fill: #6e7681; }
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
        print(f"{f['name']}: {len(f['repos'])} repos, followers={f['followers']}")


if __name__ == "__main__":
    main()
