#!/usr/bin/env python3
"""
Fetches live GitHub GraphQL telemetry for Praashon and renders the animated
assets/stats-hud.svg dashboard. Uses Python standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USERNAME = os.environ.get("GITHUB_USERNAME", "Praashon")
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
OUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "stats-hud.svg"

EXCLUDED_MARKUP = {"HTML", "CSS", "SCSS", "Sass", "Less", "TeX", "Makefile", "Batchfile", "PowerShell"}

LANG_FALLBACK_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f7df1e",
    "Rust": "#f97316",
    "C": "#34d399",
    "Python": "#38bdf8",
    "C#": "#a855f7",
    "PHP": "#818cf8",
    "PLpgSQL": "#2dd4bf",
    "Solidity": "#cbd5e1",
    "Java": "#fb923c",
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
    repositories(first: 100, privacy: PUBLIC, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        name
        stargazerCount
        forkCount
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
  }
}
"""


def fetch_graphql(login: str, token: str) -> dict:
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": login}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Praashon-Profile-Telemetry",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]["user"]


def build_smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        return f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    cmds = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        cx = (x0 + x1) / 2.0
        cmds.append(f"C {cx:.1f} {y0:.1f}, {cx:.1f} {y1:.1f}, {x1:.1f} {y1:.1f}")
    return " ".join(cmds)


def render_svg(user: dict) -> str:
    contrib = user["contributionsCollection"]
    cal = contrib["contributionCalendar"]
    repos = user["repositories"]

    total_contrib = int(cal["totalContributions"])
    commits = int(contrib["totalCommitContributions"])
    prs = int(contrib["totalPullRequestContributions"])
    public_repos = int(repos["totalCount"])
    stars = sum(int(n["stargazerCount"]) for n in repos["nodes"])
    forks = sum(int(n["forkCount"]) for n in repos["nodes"])

    # Compute primary code language distribution
    lang_bytes: dict[str, int] = {}
    lang_repos: dict[str, int] = {}
    lang_colors: dict[str, str] = {}

    for node in repos["nodes"]:
        seen_in_repo = set()
        for edge in node["languages"]["edges"]:
            name = edge["node"]["name"]
            size = int(edge["size"])
            color = LANG_FALLBACK_COLORS.get(name) or edge["node"].get("color") or "#38bdf8"
            lang_bytes[name] = lang_bytes.get(name, 0) + size
            lang_colors[name] = color
            if name not in seen_in_repo:
                lang_repos[name] = lang_repos.get(name, 0) + 1
                seen_in_repo.add(name)

    code_langs = [(k, v) for k, v in lang_bytes.items() if k not in EXCLUDED_MARKUP]
    if len(code_langs) < 5:
        code_langs = list(lang_bytes.items())
    code_langs.sort(key=lambda kv: kv[1], reverse=True)
    top_langs = code_langs[:6]
    total_lang_bytes = sum(v for _, v in top_langs) or 1

    # Segmented bar segments inside x=18..428 (width 410)
    bar_x = 18.0
    bar_total_w = 410.0
    bar_segments = []
    for idx, (lname, lsize) in enumerate(top_langs):
        pct = lsize / total_lang_bytes
        seg_w = max(6.0, bar_total_w * pct)
        if idx == len(top_langs) - 1:
            seg_w = max(4.0, (18.0 + bar_total_w) - bar_x)
        color = lang_colors.get(lname, "#38bdf8")
        bar_segments.append(
            f'<rect x="{bar_x:.1f}" y="38" width="{seg_w:.1f}" height="10" fill="{color}"/>'
        )
        bar_x += seg_w

    # 2x3 language legend inside right panel (446x128)
    legend_parts = []
    for idx, (lname, lsize) in enumerate(top_langs):
        col = idx % 2
        row = idx // 2
        lx = 18 + col * 212
        ly = 72 + row * 22
        pct = (lsize / total_lang_bytes) * 100.0
        color = lang_colors.get(lname, "#38bdf8")
        rcount = lang_repos.get(lname, 0)
        legend_parts.append(
            f'<circle cx="{lx + 4}" cy="{ly - 4}" r="3.6" fill="{color}"/>'
            f'<text x="{lx + 15}" y="{ly}" class="mono" font-size="11" font-weight="600" fill="#e2e8f0">{escape(lname)}</text>'
            f'<text x="{lx + 194}" y="{ly}" text-anchor="end" class="mono" font-size="10.5" fill="#94a3b8">{pct:4.1f}% · {rcount}r</text>'
        )

    # Last 24 weeks contribution heartbeat
    weeks = cal["weeks"][-24:]
    weekly_counts = [sum(int(d["contributionCount"]) for d in w["contributionDays"]) for w in weeks]
    if not weekly_counts:
        weekly_counts = [0] * 24
    peak = max(weekly_counts)
    active_weeks = sum(1 for c in weekly_counts if c > 0)
    scale_max = max(peak, 1)

    gx0, gx1 = 22.0, 886.0
    gy_base, gy_top = 56.0, 22.0
    step = (gx1 - gx0) / max(len(weekly_counts) - 1, 1)

    pts: list[tuple[float, float]] = []
    dots_svg = []
    for i, val in enumerate(weekly_counts):
        px = gx0 + i * step
        py = gy_base - (val / scale_max) * (gy_base - gy_top)
        pts.append((px, py))
        if val > 0:
            r = 3.0 if val == peak else 2.1
            c = "#34d399" if val == peak else "#38bdf8"
            dots_svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{c}" fill-opacity="0.9"/>')

    wave_path = build_smooth_path(pts)
    area_path = f"{wave_path} L {pts[-1][0]:.1f} {gy_base:.1f} L {pts[0][0]:.1f} {gy_base:.1f} Z"
    synced_date = datetime.now(timezone.utc).strftime("%Y-%m-%d UTC")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="278" viewBox="0 0 960 278" fill="none" role="img" aria-label="Live GitHub Telemetry Dashboard for {escape(USERNAME)}">
  <defs>
    <clipPath id="hud-clip">
      <rect x="4" y="4" width="952" height="270" rx="16"/>
    </clipPath>
    <clipPath id="lang-bar-clip">
      <rect x="18" y="38" width="410" height="10" rx="5"/>
    </clipPath>
    <linearGradient id="hud-bg" x1="0" y1="0" x2="960" y2="278" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#060a14"/>
      <stop offset="50%" stop-color="#0b1222"/>
      <stop offset="100%" stop-color="#070c17"/>
    </linearGradient>
    <linearGradient id="lang-shimmer" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="50%" stop-color="#ffffff" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="ekg-stroke" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#34d399"/>
      <stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
    <linearGradient id="ekg-area" x1="0" y1="20" x2="0" y2="58" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
    </linearGradient>
    <filter id="hud-glow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="2.6" result="b"/>
      <feMerge>
        <feMergeNode in="b"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <style>
    .mono {{ font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace; }}
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
  </style>

  <g clip-path="url(#hud-clip)">
    <rect x="4" y="4" width="952" height="270" fill="url(#hud-bg)"/>

    <!-- Header Strip -->
    <text x="26" y="29" class="mono" font-size="11" font-weight="700" fill="#94a3b8" letter-spacing="1.4">LIVE GITHUB TELEMETRY  <tspan fill="#38bdf8">//</tspan>  @{escape(USERNAME.upper())}</text>
    <circle cx="774" cy="25" r="3" fill="#34d399">
      <animate attributeName="opacity" values="1;0.25;1" dur="2s" repeatCount="indefinite"/>
    </circle>
    <text x="784" y="29" class="mono" font-size="10.5" fill="#6ee7b7">SYNCED · {synced_date}</text>
    <line x1="24" y1="39" x2="936" y2="39" stroke="#1e293b" stroke-width="1"/>

    <!-- LEFT 2x2 TELEMETRY STAT TILES -->
    <!-- Tile 1: Contributions -->
    <g transform="translate(24, 50)">
      <rect x="0" y="0" width="214" height="58" rx="10" fill="#0c1425" stroke="#38bdf8" stroke-opacity="0.26"/>
      <rect x="0" y="10" width="3.5" height="38" rx="1.75" fill="#38bdf8"/>
      <text x="16" y="28" class="sans" font-size="22" font-weight="800" fill="#f8fafc">{total_contrib:,}</text>
      <text x="16" y="46" class="mono" font-size="9.8" font-weight="600" fill="#7dd3fc" letter-spacing="0.8">CONTRIBUTIONS (1Y)</text>
      <g transform="translate(184, 29)">
        <circle cx="0" cy="0" r="13" stroke="#38bdf8" stroke-opacity="0.25" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="13" stroke="#38bdf8" stroke-width="1.8" stroke-dasharray="28 54" stroke-linecap="round">
          <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="6s" repeatCount="indefinite"/>
        </circle>
        <circle cx="0" cy="0" r="3" fill="#38bdf8"/>
      </g>
    </g>

    <!-- Tile 2: Public Repos -->
    <g transform="translate(250, 50)">
      <rect x="0" y="0" width="214" height="58" rx="10" fill="#0c1425" stroke="#34d399" stroke-opacity="0.26"/>
      <rect x="0" y="10" width="3.5" height="38" rx="1.75" fill="#34d399"/>
      <text x="16" y="28" class="sans" font-size="22" font-weight="800" fill="#f8fafc">{public_repos}</text>
      <text x="16" y="46" class="mono" font-size="9.8" font-weight="600" fill="#6ee7b7" letter-spacing="0.8">PUBLIC ORIGINAL REPOS</text>
      <g transform="translate(184, 29)">
        <circle cx="0" cy="0" r="13" stroke="#34d399" stroke-opacity="0.25" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="13" stroke="#34d399" stroke-width="1.8" stroke-dasharray="34 48" stroke-linecap="round">
          <animateTransform attributeName="transform" type="rotate" from="360" to="0" dur="7s" repeatCount="indefinite"/>
        </circle>
        <circle cx="0" cy="0" r="3" fill="#34d399"/>
      </g>
    </g>

    <!-- Tile 3: Commits & PRs -->
    <g transform="translate(24, 120)">
      <rect x="0" y="0" width="214" height="58" rx="10" fill="#0c1425" stroke="#a78bfa" stroke-opacity="0.26"/>
      <rect x="0" y="10" width="3.5" height="38" rx="1.75" fill="#a78bfa"/>
      <text x="16" y="28" class="sans" font-size="21" font-weight="800" fill="#f8fafc">{commits:,} <tspan font-size="12.5" font-weight="600" fill="#c4b5fd">/ {prs} PRs</tspan></text>
      <text x="16" y="46" class="mono" font-size="9.5" font-weight="600" fill="#c4b5fd" letter-spacing="0.7">COMMITS &amp; PULL REQUESTS</text>
      <g transform="translate(184, 29)">
        <circle cx="0" cy="0" r="13" stroke="#a78bfa" stroke-opacity="0.25" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="13" stroke="#a78bfa" stroke-width="1.8" stroke-dasharray="22 60" stroke-linecap="round">
          <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="5.2s" repeatCount="indefinite"/>
        </circle>
        <circle cx="0" cy="0" r="3" fill="#a78bfa"/>
      </g>
    </g>

    <!-- Tile 4: Stars & Forks -->
    <g transform="translate(250, 120)">
      <rect x="0" y="0" width="214" height="58" rx="10" fill="#0c1425" stroke="#fbbf24" stroke-opacity="0.26"/>
      <rect x="0" y="10" width="3.5" height="38" rx="1.75" fill="#fbbf24"/>
      <text x="16" y="28" class="sans" font-size="21" font-weight="800" fill="#f8fafc">{stars} ★ <tspan font-size="12.5" font-weight="600" fill="#fcd34d">· {forks} forks</tspan></text>
      <text x="16" y="46" class="mono" font-size="9.5" font-weight="600" fill="#fcd34d" letter-spacing="0.7">COMMUNITY RECOGNITION</text>
      <g transform="translate(184, 29)">
        <circle cx="0" cy="0" r="13" stroke="#fbbf24" stroke-opacity="0.25" stroke-width="1.5"/>
        <circle cx="0" cy="0" r="13" stroke="#fbbf24" stroke-width="1.8" stroke-dasharray="30 52" stroke-linecap="round">
          <animateTransform attributeName="transform" type="rotate" from="360" to="0" dur="6.4s" repeatCount="indefinite"/>
        </circle>
        <circle cx="0" cy="0" r="3" fill="#fbbf24"/>
      </g>
    </g>

    <!-- RIGHT PANEL: PRIMARY CODE LANGUAGES -->
    <g transform="translate(490, 50)">
      <rect x="0" y="0" width="446" height="128" rx="12" fill="#0c1425" stroke="#1e293b" stroke-width="1.1"/>
      <text x="18" y="24" class="mono" font-size="10.5" font-weight="700" fill="#94a3b8" letter-spacing="1.1">PRIMARY CODE LANGUAGES</text>
      <text x="428" y="24" text-anchor="end" class="mono" font-size="10" fill="#64748b">PUBLIC REPOS</text>

      <!-- Segmented Proportional Bar + Animated Shimmer -->
      <g clip-path="url(#lang-bar-clip)">
        {"".join(bar_segments)}
        <rect x="-120" y="38" width="120" height="10" fill="url(#lang-shimmer)">
          <animate attributeName="x" values="-120;446" dur="3.6s" repeatCount="indefinite"/>
        </rect>
      </g>

      <!-- Legend -->
      {"".join(legend_parts)}
    </g>

    <!-- BOTTOM PANEL: 24-WEEK LIVE COMMIT HEARTBEAT WAVEFORM -->
    <g transform="translate(24, 192)">
      <rect x="0" y="0" width="912" height="68" rx="12" fill="#0a1120" stroke="#1e293b" stroke-width="1.1"/>
      <text x="18" y="16" class="mono" font-size="9.8" font-weight="700" fill="#7dd3fc" letter-spacing="1">24-WEEK CONTRIBUTION HEARTBEAT</text>
      <text x="894" y="16" text-anchor="end" class="mono" font-size="9.8" fill="#94a3b8">PEAK: <tspan fill="#34d399" font-weight="700">{peak}/WK</tspan>  ·  ACTIVE: <tspan fill="#38bdf8" font-weight="700">{active_weeks}/24 WKS</tspan></text>

      <!-- Subtle baseline -->
      <line x1="22" y1="56" x2="886" y2="56" stroke="#1e293b" stroke-width="1"/>

      <!-- Area Fill + Glowing EKG Curve -->
      <path d="{area_path}" fill="url(#ekg-area)"/>
      <path d="{wave_path}" stroke="url(#ekg-stroke)" stroke-width="2" fill="none" stroke-linecap="round"/>

      <!-- Real Weekly Contribution Nodes -->
      {"".join(dots_svg)}

      <!-- Glowing Tracer Comet Gliding Along Real Commit Curve -->
      <circle r="4.2" fill="#34d399" filter="url(#hud-glow)">
        <animateMotion dur="6.2s" repeatCount="indefinite" path="{wave_path}"/>
      </circle>
      <circle r="2.2" fill="#ffffff">
        <animateMotion dur="6.2s" repeatCount="indefinite" path="{wave_path}"/>
      </circle>
    </g>
  </g>

  <rect x="4" y="4" width="952" height="270" rx="16" stroke="#1e293b" stroke-width="1.2"/>
</svg>
'''


def main() -> int:
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        return 1
    user = fetch_graphql(USERNAME, TOKEN)
    svg = render_svg(user)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(svg, encoding="utf-8")
    print(f"Updated {OUT_PATH} successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
