#!/usr/bin/env python3
"""
Fetches live GitHub GraphQL metrics for Praashon and generates minimal dark & light
editorial overview SVGs (assets/overview-dark.svg and assets/overview-light.svg).
Uses Python standard library only.
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
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

EXCLUDED_MARKUP = {"HTML", "CSS", "SCSS", "Sass", "Less", "TeX", "Makefile", "Batchfile", "PowerShell"}

# Muted, cohesive editorial palette (not neon)
MUTED_LANG_COLORS = {
    "dark": {
        "TypeScript": "#58a6ff",
        "C": "#34b88a",
        "JavaScript": "#d2a85b",
        "Rust": "#d18661",
        "Python": "#79c0ff",
        "C#": "#a38ce0",
        "PHP": "#8b949e",
    },
    "light": {
        "TypeScript": "#2b6cb0",
        "C": "#15996c",
        "JavaScript": "#b78428",
        "Rust": "#b55d35",
        "Python": "#3b82a6",
        "C#": "#755bb5",
        "PHP": "#6b6b66",
    },
}

THEMES = {
    "dark": {
        "card": "#11161f",
        "border": "#21262d",
        "hairline": "#21262d",
        "ink": "#f0f3f6",
        "sub": "#8b949e",
        "muted": "#6e7681",
        "accent": "#34b88a",
        "bar_bg": "#1b212c",
    },
    "light": {
        "card": "#f4f4f0",
        "border": "#e4e4df",
        "hairline": "#e4e4df",
        "ink": "#2a2a28",
        "sub": "#63635e",
        "muted": "#8a8a83",
        "accent": "#15996c",
        "bar_bg": "#e4e4df",
    },
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
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
            "User-Agent": "Praashon-Profile-Overview",
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


def render_overview(user: dict, mode: str) -> str:
    t = THEMES[mode]
    lang_palette = MUTED_LANG_COLORS[mode]

    contrib = user["contributionsCollection"]
    cal = contrib["contributionCalendar"]
    repos = user["repositories"]

    total_contrib = int(cal["totalContributions"])
    commits = int(contrib["totalCommitContributions"])
    public_repos = int(repos["totalCount"])

    # Primary code languages
    lang_bytes: dict[str, int] = {}
    for node in repos["nodes"]:
        for edge in node["languages"]["edges"]:
            name = edge["node"]["name"]
            lang_bytes[name] = lang_bytes.get(name, 0) + int(edge["size"])

    code_langs = [(k, v) for k, v in lang_bytes.items() if k not in EXCLUDED_MARKUP]
    if len(code_langs) < 5:
        code_langs = list(lang_bytes.items())
    code_langs.sort(key=lambda kv: kv[1], reverse=True)
    top_langs = code_langs[:5]
    total_bytes = sum(v for _, v in top_langs) or 1

    # Ultra-slim segmented bar inside x=492..872 (width 380)
    bar_x = 492.0
    bar_w = 380.0
    bar_rects = []
    legend_items = []
    for idx, (lname, lsize) in enumerate(top_langs):
        pct = lsize / total_bytes
        seg_w = max(5.0, bar_w * pct)
        if idx == len(top_langs) - 1:
            seg_w = max(4.0, (492.0 + bar_w) - bar_x)
        color = lang_palette.get(lname, t["sub"])
        bar_rects.append(f'<rect x="{bar_x:.1f}" y="114" width="{seg_w:.1f}" height="5" fill="{color}"/>')
        bar_x += seg_w
        short = "JS" if lname == "JavaScript" else ("TS" if lname == "TypeScript" else lname)
        legend_items.append((short, round(pct * 100), color))

    # Build evenly spaced minimalist legend on one crisp row
    lx = 492
    legend_svg = []
    for short, pct_int, color in legend_items:
        label = f"{short} {pct_int}%"
        legend_svg.append(
            f'<circle cx="{lx + 3}" cy="133" r="2.8" fill="{color}"/>'
            f'<text x="{lx + 11}" y="136.5" class="mono" font-size="10.2" fill="{t["sub"]}">{escape(label)}</text>'
        )
        lx += max(64, int(len(label) * 6.5 + 22))

    # 24-week calm sparkline inside x=492..872, y=162..196
    weeks = cal["weeks"][-24:]
    weekly = [sum(int(d["contributionCount"]) for d in w["contributionDays"]) for w in weeks]
    if not weekly:
        weekly = [0] * 24
    scale_max = max(max(weekly), 1)
    gx0, gx1 = 492.0, 872.0
    gy_base, gy_top = 196.0, 162.0
    step = (gx1 - gx0) / max(len(weekly) - 1, 1)

    pts = [(gx0 + i * step, gy_base - (v / scale_max) * (gy_base - gy_top)) for i, v in enumerate(weekly)]
    spark_path = build_smooth_path(pts)
    area_path = f"{spark_path} L {pts[-1][0]:.1f} {gy_base:.1f} L {pts[0][0]:.1f} {gy_base:.1f} Z"
    synced = datetime.now(timezone.utc).strftime("%b %d, %Y")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="224" viewBox="0 0 900 224" fill="none" role="img" aria-label="Stack and Live GitHub Activity for {escape(USERNAME)}">
  <defs>
    <clipPath id="ov-frame-{mode}">
      <rect x="0.5" y="0.5" width="899" height="223" rx="12"/>
    </clipPath>
    <clipPath id="ov-bar-clip-{mode}">
      <rect x="492" y="114" width="0" height="5" rx="2.5">
        <animate attributeName="width" from="0" to="380" dur="1.0s" begin="0.3s" calcMode="spline" keyTimes="0;1" keySplines="0.16 1 0.3 1" fill="freeze"/>
      </rect>
    </clipPath>
    <linearGradient id="ov-area-{mode}" x1="0" y1="160" x2="0" y2="198" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="{t["accent"]}" stop-opacity="0.14"/>
      <stop offset="100%" stop-color="{t["accent"]}" stop-opacity="0"/>
    </linearGradient>
  </defs>

  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace; }}
    .in-1 {{ animation: rise 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.12s both; }}
    .in-2 {{ animation: rise 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.24s both; }}
    .spark-draw {{
      stroke-dasharray: 100;
      stroke-dashoffset: 100;
      animation: strokeDraw 1.25s cubic-bezier(0.16, 1, 0.3, 1) 0.38s forwards;
    }}
    .area-fade {{ animation: fadeIn 0.9s ease 0.75s both; }}
    @keyframes rise {{
      from {{ transform: translateY(10px); opacity: 0; }}
      to {{ transform: translateY(0); opacity: 1; }}
    }}
    @keyframes strokeDraw {{
      to {{ stroke-dashoffset: 0; }}
    }}
    @keyframes fadeIn {{
      from {{ opacity: 0; }}
      to {{ opacity: 1; }}
    }}
  </style>

  <g clip-path="url(#ov-frame-{mode})">
    <rect x="0" y="0" width="900" height="224" fill="{t["card"]}"/>

    <!-- LEFT COLUMN: STACK & FOCUS -->
    <g class="in-1">
      <text x="28" y="32" class="mono" font-size="10" font-weight="500" fill="{t["muted"]}" letter-spacing="1.4">03  /  STACK &amp; DISCIPLINES</text>

      <text x="28" y="68" class="mono" font-size="11" fill="{t["accent"]}">Systems</text>
      <text x="114" y="68" class="sans" font-size="12.8" fill="{t["ink"]}">Rust, C, WebAssembly, C#, Python</text>
      <line x1="28" y1="84" x2="434" y2="84" stroke="{t["hairline"]}" stroke-width="1"/>

      <text x="28" y="109" class="mono" font-size="11" fill="{t["accent"]}">Interface</text>
      <text x="114" y="109" class="sans" font-size="12.8" fill="{t["ink"]}">TypeScript, React, Next.js, Tailwind, Three.js, GSAP</text>
      <line x1="28" y1="125" x2="434" y2="125" stroke="{t["hairline"]}" stroke-width="1"/>

      <text x="28" y="150" class="mono" font-size="11" fill="{t["accent"]}">Backend</text>
      <text x="114" y="150" class="sans" font-size="12.8" fill="{t["ink"]}">Node.js, FastAPI, PostgreSQL, Supabase, Redis, LLMs</text>
      <line x1="28" y1="166" x2="434" y2="166" stroke="{t["hairline"]}" stroke-width="1"/>

      <text x="28" y="191" class="mono" font-size="11" fill="{t["accent"]}">Tooling</text>
      <text x="114" y="191" class="sans" font-size="12.8" fill="{t["ink"]}">Electron, ADB / SCRCPY, Chrome MV3, Linux</text>
    </g>

    <!-- Center Hairline Divider -->
    <line x1="462" y1="24" x2="462" y2="200" stroke="{t["hairline"]}" stroke-width="1"/>

    <!-- RIGHT COLUMN: LIVE ACTIVITY -->
    <g class="in-2">
      <text x="492" y="32" class="mono" font-size="10" font-weight="500" fill="{t["muted"]}" letter-spacing="1.4">ACTIVITY</text>
      <text x="872" y="32" text-anchor="end" class="mono" font-size="10" fill="{t["muted"]}">Updated {synced}</text>

      <!-- 3 Clean Editorial Metrics -->
      <text x="492" y="72" class="sans" font-size="25" font-weight="700" fill="{t["ink"]}" letter-spacing="-0.6">{total_contrib:,}</text>
      <text x="492" y="90" class="mono" font-size="9.5" fill="{t["muted"]}" letter-spacing="1.1">CONTRIBUTIONS</text>

      <text x="634" y="72" class="sans" font-size="25" font-weight="700" fill="{t["ink"]}" letter-spacing="-0.6">{public_repos}</text>
      <text x="634" y="90" class="mono" font-size="9.5" fill="{t["muted"]}" letter-spacing="1.1">PUBLIC REPOS</text>

      <text x="766" y="72" class="sans" font-size="25" font-weight="700" fill="{t["ink"]}" letter-spacing="-0.6">{commits:,}</text>
      <text x="766" y="90" class="mono" font-size="9.5" fill="{t["muted"]}" letter-spacing="1.1">COMMITS (1Y)</text>

      <!-- Slim Language Bar -->
      <rect x="492" y="114" width="380" height="5" rx="2.5" fill="{t["bar_bg"]}"/>
      <g clip-path="url(#ov-bar-clip-{mode})">
        {"".join(bar_rects)}
      </g>
      {"".join(legend_svg)}

      <!-- Minimal 24-Week Sparkline -->
      <line x1="492" y1="196" x2="872" y2="196" stroke="{t["hairline"]}" stroke-width="1"/>
      <path d="{area_path}" fill="url(#ov-area-{mode})" class="area-fade"/>
      <path d="{spark_path}" pathLength="100" stroke="{t["accent"]}" stroke-width="1.6" fill="none" stroke-linecap="round" class="spark-draw"/>
      <text x="872" y="210" text-anchor="end" class="mono" font-size="9.2" fill="{t["muted"]}" letter-spacing="0.8">24-WEEK CADENCE</text>
    </g>
  </g>

  <rect x="0.5" y="0.5" width="899" height="223" rx="12" stroke="{t["border"]}" stroke-width="1"/>
</svg>
'''


def main() -> int:
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN environment variable is required.", file=sys.stderr)
        return 1
    user = fetch_graphql(USERNAME, TOKEN)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for mode in ("dark", "light"):
        out = ASSETS_DIR / f"overview-{mode}.svg"
        out.write_text(render_overview(user, mode), encoding="utf-8")
        print(f"Updated {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
