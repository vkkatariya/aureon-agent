#!/usr/bin/env python3
"""Generate a pixel-style AUREON-AGENT banner SVG.

Pixel-art aesthetic: blocky, retro-tech, sharp edges, big bold wordmark.
Each letter rendered on a 5x7 pixel grid, scaled 12x.

Output: assets/banner.svg (one file, ~6-10 KB).
"""
from __future__ import annotations

import sys
from pathlib import Path

# 5x7 pixel font. Each char = list of 7 strings, each 5 chars wide.
# '#' = filled pixel, ' ' = empty. Designed for high legibility at small sizes.
FONT_5x7 = {
    "A": [
        " ### ",
        "#   #",
        "#   #",
        "#####",
        "#   #",
        "#   #",
        "#   #",
    ],
    "U": [
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ],
    "R": [
        "#### ",
        "#   #",
        "#   #",
        "#### ",
        "# #  ",
        "#  # ",
        "#   #",
    ],
    "E": [
        "#####",
        "#    ",
        "#    ",
        "#### ",
        "#    ",
        "#    ",
        "#####",
    ],
    "O": [
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ],
    "N": [
        "#   #",
        "##  #",
        "# # #",
        "# # #",
        "#  ##",
        "#   #",
        "#   #",
    ],
    "G": [
        " ### ",
        "#   #",
        "#    ",
        "# ###",
        "#   #",
        "#   #",
        " ### ",
    ],
    "T": [
        "#####",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
    ],
    "-": [
        "     ",
        "     ",
        "     ",
        " ### ",
        "     ",
        "     ",
        "     ",
    ],
    " ": [
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
    ],
}


def render_text(text: str, pixel_size: int, color: str, gap: int = 1) -> tuple[str, int, int]:
    """Render text to SVG <rect> elements. Returns (svg_fragment, width, height)."""
    rects = []
    char_w = 5
    char_h = 7
    advance = char_w + gap

    x = 0
    y = 0
    for ch in text:
        glyph = FONT_5x7.get(ch.upper(), FONT_5x7[" "])
        for row in range(char_h):
            for col in range(char_w):
                if glyph[row][col] == "#":
                    rects.append(
                        f'<rect x="{x + col * pixel_size}" '
                        f'y="{y + row * pixel_size}" '
                        f'width="{pixel_size}" '
                        f'height="{pixel_size}" '
                        f'fill="{color}"/>'
                    )
        x += advance * pixel_size

    total_w = x - gap * pixel_size  # remove trailing gap
    total_h = char_h * pixel_size
    return "\n    ".join(rects), total_w, total_h


def make_banner() -> str:
    # Banner dimensions: 1200x300, 12x pixel size, 1px gap
    pixel = 12
    gap = 1
    text = "AUREON-AGENT"
    color_main = "#FF8A2B"  # warm orange
    color_glow = "#FFB347"  # lighter highlight for drop shadow
    #    color_dark = "#1A1A1A"  # bg

    main_w = 12 * (5 * len(text) + (len(text) - 1) * 1) - 1
    # banner is 1200 wide. Center the wordmark.
    banner_w = 1200
    banner_h = 300
    offset_x = (banner_w - main_w) // 2
    offset_y = (banner_h - 7 * pixel) // 2

    # Shadow layer: render with dark color, no per-rect fill (use group fill)
    shadow_rects, _, _ = render_text(text, pixel, "currentColor", gap)
    # Main layer: render with per-rect fill (gradient)
    main_rects, _, _ = render_text(text, pixel, "url(#mainGrad)", gap)

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {banner_w} {banner_h}" width="{banner_w}" height="{banner_h}" role="img" aria-label="AUREON-AGENT — personal AI agent">
  <title>AUREON-AGENT</title>
  <desc>Pixel-style wordmark for aureon-agent, a personal AI agent built by Vishal Katariya.</desc>
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0D0D0D"/>
      <stop offset="100%" stop-color="#1A1A1A"/>
    </linearGradient>
    <linearGradient id="mainGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#FFD24A"/>
      <stop offset="50%" stop-color="#FF8A2B"/>
      <stop offset="100%" stop-color="#E85D04"/>
    </linearGradient>
  </defs>
  <!-- dark background -->
  <rect x="0" y="0" width="{banner_w}" height="{banner_h}" fill="url(#bgGrad)"/>
  <!-- top accent bar -->
  <rect x="0" y="0" width="{banner_w}" height="4" fill="#E85D04"/>
  <!-- bottom accent bar -->
  <rect x="0" y="{banner_h - 4}" width="{banner_w}" height="4" fill="#E85D04"/>
  <!-- drop shadow (offset +4, +4) -->
  <g transform="translate({offset_x + 4}, {offset_y + 4})" fill="#3A1A00" opacity="0.55">
    {shadow_rects}
  </g>
  <!-- main wordmark -->
  <g transform="translate({offset_x}, {offset_y})" fill="url(#mainGrad)">
    {main_rects}
  </g>
  <!-- caption strip -->
  <g font-family="ui-monospace, 'SF Mono', Menlo, Consolas, monospace" font-size="14" fill="#A0A0A0">
    <text x="40" y="{banner_h - 28}" letter-spacing="2">PERSONAL AI AGENT  ·  v0.1  ·  OLLAMA + TELEGRAM  ·  DOCTRINE-AWARE</text>
    <text x="{banner_w - 280}" y="{banner_h - 28}" letter-spacing="2">github.com/vkkatariya/aureon-agent</text>
  </g>
</svg>
'''
    return svg


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "assets" / "banner.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(make_banner(), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
