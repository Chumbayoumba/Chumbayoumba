#!/usr/bin/env python3
"""Builds the SVG images of the profile README: the hero, project cards and GitHub stats, each in a dark and a light
variant (the README picks one with <picture> and prefers-color-scheme).

Text is shaped with HarfBuzz and written as outlines, so the images look the same everywhere and need no web fonts
(GitHub serves README images from a sandbox that blocks font loading). Stats come from the GitHub GraphQL API; set
GITHUB_TOKEN (the Actions token is enough). Without it the last stats in assets/stats.json are reused.

    pip install uharfbuzz fonttools
    GITHUB_TOKEN=... python tools/build.py
"""

import json
import math
import os
import pathlib
import urllib.request

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "tools" / "fonts"
ASSETS = ROOT / "assets"
PROFILE = json.loads((ROOT / "tools" / "profile.json").read_text(encoding="utf-8"))

THEMES = {
    "dark": {
        "bg": "#0b0d12",
        "surface": "#11151c",
        "chip": "#171c25",
        "border": "#252b37",
        "text": "#f3f5f9",
        "muted": "#a3acbb",
        "faint": "#6f7888",
        "a": "#8b5cf6",
        "b": "#22d3ee",
        "name": ["#ffffff", "#c4b5fd"],
        "glow": 0.34,
        "live": "#4ade80",
    },
    "light": {
        "bg": "#ffffff",
        "surface": "#f8f9fb",
        "chip": "#ffffff",
        "border": "#e2e6ed",
        "text": "#0e1116",
        "muted": "#4a5361",
        "faint": "#6b7482",
        "a": "#7c3aed",
        "b": "#0891b2",
        "name": ["#0e1116", "#5b21b6"],
        "glow": 0.16,
        "live": "#16a34a",
    },
}

MOTION = """
@keyframes drift { 0%, 100% { transform: translate(0, 0) } 50% { transform: translate(-46px, 26px) } }
@keyframes drift2 { 0%, 100% { transform: translate(0, 0) } 50% { transform: translate(38px, -30px) } }
@keyframes ping { 0% { transform: scale(1); opacity: .55 } 80%, 100% { transform: scale(2.8); opacity: 0 } }
.drift { animation: drift 18s ease-in-out infinite }
.drift2 { animation: drift2 22s ease-in-out infinite }
.ping { transform-box: fill-box; transform-origin: center; animation: ping 2.4s cubic-bezier(0, 0, .2, 1) infinite }
@media (prefers-reduced-motion: reduce) { * { animation: none !important } }
"""


def num(value):
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


class Face:
    """One weight of a variable font: shapes text with HarfBuzz and draws it as SVG path data."""

    def __init__(self, file, weight):
        self.face = hb.Face(hb.Blob.from_file_path(str(FONTS / file)))
        self.font = hb.Font(self.face)
        self.font.set_variations({"wght": weight})
        self.upem = self.face.upem

    def shape(self, text, size, tracking=0.0):
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self.font, buffer, {"kern": True, "liga": True})
        scale = size / self.upem
        glyphs, x = [], 0.0
        for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions):
            glyphs.append((info.codepoint, x + pos.x_offset * scale, pos.y_offset * scale))
            x += pos.x_advance * scale + tracking
        return glyphs, max(0.0, x - tracking)

    def width(self, text, size, tracking=0.0):
        return self.shape(text, size, tracking)[1]

    def outline(self, gid):
        pen = SVGPathPen(None, ntos=lambda v: str(round(v)))
        self.font.draw_glyph_with_pen(gid, pen)
        return pen.getCommands()

    def wrap(self, text, size, width, limit):
        lines, line = [], ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and self.width(candidate, size) > width:
                lines.append(line)
                line = word
                continue
            line = candidate
        lines.append(line)
        if len(lines) <= limit:
            return lines
        last = lines[limit - 1]
        while self.width(last + "…", size) > width:
            last = last.rsplit(" ", 1)[0]
        return lines[: limit - 1] + [last + "…"]


SANS = {w: Face("Geist-VF.ttf", w) for w in (400, 500, 600, 700)}
MONO = {w: Face("GeistMono-VF.ttf", w) for w in (400, 500)}

# Glyph outlines used by the document being built, keyed by (face, glyph id). Every glyph is stored once in <defs>
# (in font units) and placed with <use>, which keeps the files several times smaller than inline paths.
GLYPHS = {}


def text(face, value, x, y, size, fill, tracking=0.0, anchor="start"):
    glyphs, width = face.shape(value, size, tracking)
    x -= {"start": 0, "middle": width / 2, "end": width}[anchor]
    scale = f"{size / face.upem:.5f}".rstrip("0")
    uses = []
    for gid, gx, gy in glyphs:
        key = (id(face), gid)
        if key not in GLYPHS:
            GLYPHS[key] = (f"g{len(GLYPHS)}", face.outline(gid))
        if GLYPHS[key][1]:
            uses.append(
                f'<use href="#{GLYPHS[key][0]}" transform="matrix({scale} 0 0 -{scale} {num(x + gx)} {num(y - gy)})"/>'
            )
    return f'<g fill="{fill}">{"".join(uses)}</g>'


def escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def document(width, height, title, body, defs="", motion=False):
    style = f"<style>{MOTION}</style>" if motion else ""
    glyphs = "".join(f'<path id="{name}" d="{outline}"/>' for name, outline in GLYPHS.values() if outline)
    GLYPHS.clear()
    defs += glyphs
    title = escape(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{title}"><title>{title}</title>{style}<defs>{defs}</defs>{body}</svg>\n'
    )


def chips(items, x, y, theme, size=12.5, height=30, gap=8, max_width=10_000):
    parts, cursor = [], x
    for item in items:
        width = MONO[400].width(item, size) + 24
        if cursor + width - x > max_width:
            break
        parts.append(
            f'<rect x="{num(cursor)}" y="{y}" width="{num(width)}" height="{height}" rx="{height / 2}" '
            f'fill="{theme["chip"]}" stroke="{theme["border"]}"/>'
        )
        parts.append(text(MONO[400], item, cursor + 12, y + height / 2 + size * 0.36, size, theme["muted"]))
        cursor += width + gap
    return "".join(parts)


def star(x, y, count, theme):
    # Geist has no ★, so the star is drawn: a 12 px five-point star centered on (x + 6, y - 4).
    points = " ".join(
        f"{num(x + 6 + r * math.sin(i * 0.6283185))},{num(y - 4 - r * math.cos(i * 0.6283185))}"
        for i, r in enumerate([6.2, 2.6] * 5)
    )
    return (
        f'<polygon points="{points}" fill="{theme["faint"]}"/>'
        + text(MONO[400], str(count), x + 17, y, 12.5, theme["faint"])
    )


def mark(x, y, size, color):
    # The Unvara mark: an open ring with a spark leaving through the gap.
    scale = size / 24
    return (
        f'<g transform="translate({x} {y}) scale({num(scale)})" fill="none">'
        f'<path d="M15.38 5.25A8 8 0 1 1 8.62 5.25" stroke="{color}" stroke-width="2.25" stroke-linecap="round"/>'
        f'<circle cx="12" cy="3.6" r="1.7" fill="{color}"/></g>'
    )


def hero(theme):
    width, height = 1200, 420
    now = PROFILE["now"]
    defs = (
        f'<clipPath id="frame"><rect width="{width}" height="{height}" rx="28"/></clipPath>'
        f'<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse">'
        f'<circle cx="2" cy="2" r="1.2" fill="{theme["border"]}"/></pattern>'
        f'<radialGradient id="fade" cx="0.3" cy="0.35" r="0.75"><stop offset="0" stop-color="#fff"/>'
        f'<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>'
        f'<mask id="fadeMask"><rect width="{width}" height="{height}" fill="url(#fade)"/></mask>'
        f'<radialGradient id="glowA"><stop offset="0" stop-color="{theme["a"]}" stop-opacity="{theme["glow"]}"/>'
        f'<stop offset="1" stop-color="{theme["a"]}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="glowB"><stop offset="0" stop-color="{theme["b"]}" stop-opacity="{theme["glow"]}"/>'
        f'<stop offset="1" stop-color="{theme["b"]}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="accent" gradientUnits="userSpaceOnUse" x1="64" x2="330"><stop offset="0" stop-color="{theme["a"]}"/>'
        f'<stop offset="1" stop-color="{theme["b"]}"/></linearGradient>'
        f'<linearGradient id="name" gradientUnits="userSpaceOnUse" x1="58" y1="110" x2="330" y2="220">'
        f'<stop offset="0.35" stop-color="{theme["name"][0]}"/>'
        f'<stop offset="1" stop-color="{theme["name"][1]}"/></linearGradient>'
    )
    body = [
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="28" fill="{theme["bg"]}" '
        f'stroke="{theme["border"]}"/>',
        '<g clip-path="url(#frame)">',
        f'<rect width="{width}" height="{height}" fill="url(#dots)" mask="url(#fadeMask)"/>',
        '<circle class="drift" cx="930" cy="40" r="330" fill="url(#glowA)"/>',
        '<circle class="drift2" cx="1150" cy="420" r="300" fill="url(#glowB)"/>',
        '<circle class="drift2" cx="120" cy="-40" r="260" fill="url(#glowA)" opacity="0.6"/>',
        "</g>",
        text(MONO[500], PROFILE["role"].upper(), 64, 94, 14, "url(#accent)", tracking=3.2),
        text(SANS[700], PROFILE["name"], 58, 206, 116, "url(#name)", tracking=-3),
    ]
    for index, line in enumerate(PROFILE["tagline"]):
        body.append(text(SANS[400], line, 64, 258 + index * 32, 22, theme["muted"]))
    cursor = 64
    for pill in PROFILE["pills"]:
        pill_width = SANS[500].width(pill, 14) + 30
        body.append(
            f'<rect x="{num(cursor)}" y="328" width="{num(pill_width)}" height="34" rx="17" fill="{theme["chip"]}" '
            f'stroke="{theme["border"]}"/>'
        )
        body.append(text(SANS[500], pill, cursor + 15, 350, 14, theme["muted"]))
        cursor += pill_width + 10

    card_x, card_y, card_w, card_h = 770, 56, 366, 308
    body += [
        f'<rect x="{card_x}" y="{card_y}" width="{card_w}" height="{card_h}" rx="22" fill="{theme["surface"]}" '
        f'fill-opacity="0.86" stroke="{theme["border"]}"/>',
        f'<circle class="ping" cx="{card_x + 32}" cy="{card_y + 38}" r="5" fill="{theme["live"]}"/>',
        f'<circle cx="{card_x + 32}" cy="{card_y + 38}" r="5" fill="{theme["live"]}"/>',
        text(MONO[500], "NOW BUILDING", card_x + 48, card_y + 43, 12.5, theme["faint"], tracking=2.2),
        mark(card_x + 26, card_y + 70, 42, "#e2a04f"),
        text(SANS[600], now["name"], card_x + 80, card_y + 104, 30, theme["text"], tracking=-0.4),
    ]
    for index, line in enumerate(SANS[400].wrap(now["text"], 16, card_w - 56, 3)):
        body.append(text(SANS[400], line, card_x + 28, card_y + 150 + index * 24, 16, theme["muted"]))
    body.append(chips(now["chips"], card_x + 28, card_y + 222, theme, max_width=card_w - 56))
    body.append(text(MONO[400], now["footer"], card_x + 28, card_y + 284, 13, theme["faint"]))
    title = f'{PROFILE["name"]} — {PROFILE["role"].lower()}. {" ".join(PROFILE["tagline"])}'
    return document(width, height, title, "".join(body), defs, motion=True)


BADGES = {
    "Open source": lambda theme, accent: (accent[1], accent[1]),
    "Live": lambda theme, accent: (theme["live"], theme["live"]),
    "Private": lambda theme, accent: (theme["faint"], theme["border"]),
}


def card(project, theme, stars):
    width, height = 600, 270
    accent = project["accent"]
    defs = (
        f'<clipPath id="frame"><rect width="{width}" height="{height}" rx="22"/></clipPath>'
        f'<radialGradient id="glow"><stop offset="0" stop-color="{accent[0]}" stop-opacity="{theme["glow"] * 0.8}"/>'
        f'<stop offset="1" stop-color="{accent[0]}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="icon" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{accent[0]}"/>'
        f'<stop offset="1" stop-color="{accent[1]}"/></linearGradient>'
    )
    badge = project["badge"]
    ink, stroke = BADGES[badge](theme, accent)
    badge_text = badge.upper()
    badge_width = MONO[500].width(badge_text, 11.5, 1.2) + 26
    link = project.get("url", "")
    sub = link.removeprefix("https://") if link else "Private repository"
    body = [
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="22" fill="{theme["surface"]}" '
        f'stroke="{theme["border"]}"/>',
        f'<g clip-path="url(#frame)"><circle cx="{width - 40}" cy="0" r="220" fill="url(#glow)"/></g>',
        '<rect x="32" y="32" width="48" height="48" rx="14" fill="url(#icon)"/>',
        text(SANS[700], project["name"][0].upper(), 56, 65, 24, "#ffffff", anchor="middle"),
        text(SANS[600], project["name"], 96, 60, 25, theme["text"], tracking=-0.3),
        text(MONO[400], sub, 96, 83, 12.5, theme["faint"]),
        star(96 + MONO[400].width(sub, 12.5) + 14, 79, stars, theme) if stars else "",
        f'<rect x="{num(width - 32 - badge_width)}" y="36" width="{num(badge_width)}" height="26" rx="13" '
        f'fill="none" stroke="{stroke}" stroke-opacity="0.7"/>',
        text(MONO[500], badge_text, width - 32 - badge_width / 2, 53, 11.5, ink, tracking=1.2, anchor="middle"),
    ]
    for index, line in enumerate(SANS[400].wrap(project["text"], 16, width - 64, 3)):
        body.append(text(SANS[400], line, 32, 132 + index * 25, 16, theme["muted"]))
    body.append(chips(project["chips"], 32, 210, theme, max_width=width - 64))
    title = f'{project["name"]}: {project["text"]}'
    return document(width, height, title, "".join(body), defs)


def stats(theme, data):
    width, height = 1200, 170
    metrics = [
        (f'{data["contributions"]:,}', "contributions in the last year"),
        (f'{data["activeDays"]}', "active days in the last year"),
        (f'{data["repositories"]:,}', "open-source repositories"),
        (f'{data["stars"]:,}', "stars on GitHub"),
    ]
    column = (width - 96) / len(metrics)
    body = [
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="22" fill="{theme["surface"]}" '
        f'stroke="{theme["border"]}"/>',
    ]
    for index, (value, label) in enumerate(metrics):
        x = 48 + index * column
        if index:
            body.append(
                f'<line x1="{num(x - 24)}" y1="44" x2="{num(x - 24)}" y2="126" stroke="{theme["border"]}"/>'
            )
        body.append(text(SANS[700], value, x, 98, 48, theme["text"], tracking=-1.2))
        body.append(text(SANS[400], label, x, 128, 15, theme["muted"]))
    title = ", ".join(f"{value} {label}" for value, label in metrics)
    return document(width, height, title, "".join(body))


QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar { totalContributions weeks { contributionDays { contributionCount } } }
    }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, first: 100) {
      totalCount
      nodes { nameWithOwner stargazerCount }
    }
  }
}
"""


def github():
    token = os.environ.get("GITHUB_TOKEN")
    cache = ASSETS / "stats.json"
    if not token:
        return json.loads(cache.read_text(encoding="utf-8"))
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": PROFILE["login"]}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    user = json.load(urllib.request.urlopen(request))["data"]["user"]
    repositories = user["repositories"]
    data = {
        "contributions": user["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        # The Actions token sees commits to public repositories only, but the calendar includes private work too.
        "activeDays": sum(
            1
            for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
            if day["contributionCount"] > 0
        ),
        "repositories": repositories["totalCount"],
        "stars": sum(node["stargazerCount"] for node in repositories["nodes"]),
        "repoStars": {node["nameWithOwner"]: node["stargazerCount"] for node in repositories["nodes"]},
    }
    cache.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def write(name, content):
    path = ASSETS / name
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def main():
    ASSETS.mkdir(exist_ok=True)
    data = github()
    for mode, theme in THEMES.items():
        write(f"hero-{mode}.svg", hero(theme))
        write(f"stats-{mode}.svg", stats(theme, data))
        for project in PROFILE["projects"]:
            stars = data["repoStars"].get(project["repo"]) if project.get("repo") else None
            write(f'card-{project["slug"]}-{mode}.svg', card(project, theme, stars))


if __name__ == "__main__":
    main()
