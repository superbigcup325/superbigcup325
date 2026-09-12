#!/usr/bin/env python3
"""Convert pokemon-colorscripts ANSI art (truecolor half-blocks) to SVG + PNG preview.

Grid model: each terminal cell = 2 stacked pixels (upper/lower).
  '█' U+2588  upper=fg      lower=fg
  '▀' U+2580  upper=fg      lower=bg
  '▄' U+2584  upper=bg      lower=fg
  ' '        transparent cell (advances column)
SGR: 38;2;R;G;B sets fg, 48;2;R;G;B sets bg, 0/empty/39/49 resets.
"""
import re
import sys
import zlib
import struct

ESC_RE = re.compile("\x1b\\[([0-9;]*)m")

BLOCKS = {"█": "full", "▀": "upper", "▄": "lower"}


def parse_grid_v2(text):
    """Robust parser: single pass with SGR token processing."""
    fg = bg = None
    rows = [[]]
    pos = 0
    for m in ESC_RE.finditer(text):
        for ch in text[pos : m.start()]:
            if ch == "\n":
                rows.append([])
            else:
                kind = BLOCKS.get(ch, "space")
                if kind == "full":
                    rows[-1].append((fg, fg))
                elif kind == "upper":
                    rows[-1].append((fg, bg))
                elif kind == "lower":
                    rows[-1].append((bg, fg))
                else:
                    rows[-1].append((None, None))
        params = [p if p else "0" for p in m.group(1).split(";")]
        i = 0
        while i < len(params):
            p = int(params[i])
            if p == 0:
                fg = bg = None
                i += 1
            elif p in (38, 48):
                # expect 2;R;G;B
                if i + 4 < len(params) + 1 and params[i + 1] == "2":
                    rgb = tuple(int(params[i + 2 + k]) for k in range(3))
                    if p == 38:
                        fg = rgb
                    else:
                        bg = rgb
                    i += 5
                else:
                    i += 1
            elif p in (39, 49):
                if p == 39:
                    fg = None
                else:
                    bg = None
                i += 1
            else:
                i += 1
        pos = m.end()
    for ch in text[pos:]:
        if ch == "\n":
            rows.append([])
        else:
            rows[-1].append((None, None))
    return rows


def trim(rows):
    """Trim fully-transparent border rows/cols."""
    if not rows:
        return rows
    def row_has(r):
        return any(u or l for u, l in r)
    top = 0
    while top < len(rows) and not row_has(rows[top]):
        top += 1
    bot = len(rows)
    while bot > top and not row_has(rows[bot - 1]):
        bot -= 1
    rows = rows[top:bot]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [(None, None)] * (width - len(r)) for r in rows]
    def col_has(c):
        return any(r[c][0] or r[c][1] for r in rows)
    left = 0
    while left < width and not col_has(left):
        left += 1
    right = width
    while right > left and not col_has(right - 1):
        right -= 1
    return [r[left:right] for r in rows]


def to_svg(rows):
    """Pixels: (y_even=upper, y_odd=lower). Merge horizontal runs. 1 unit = 1 pixel."""
    h_cells = len(rows)
    w_cells = max(len(r) for r in rows)
    w, h = w_cells, h_cells * 2
    parts = []
    for cy, row in enumerate(rows):
        for half in (0, 1):
            runs = []
            cur = None
            start = 0
            for x, cell in enumerate(row):
                c = cell[half]
                if c != cur:
                    if cur is not None:
                        runs.append((start, x, cur))
                    cur = c
                    start = x
            if cur is not None:
                runs.append((start, len(row), cur))
            for s, e, rgb in runs:
                parts.append(
                    f'<rect x="{s}" y="{cy * 2 + half}" width="{e - s}" height="1" fill="rgb{rgb}"/>'
                )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" shape-rendering="crispEdges">\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )


def write_png(path, pixels, w, h, scale):
    """pixels: flat list of (r,g,b,a) per output pixel row-major."""
    out_w, out_h = w * scale, h * scale
    raw = bytearray()
    for y in range(out_h):
        raw.append(0)  # filter none
        sy = y // scale
        row_off = sy * w
        for x in range(out_w):
            r, g, b, a = pixels[row_off + x // scale]
            raw += bytes((r, g, b, a))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", out_w, out_h, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def to_png(rows, path, scale=8, bg=(0, 0, 0, 0)):
    h_cells = len(rows)
    w_cells = max(len(r) for r in rows)
    w, h = w_cells, h_cells * 2
    px = [bg] * (w * h)
    for cy, row in enumerate(rows):
        for cx, (u, l) in enumerate(row):
            for half, c in enumerate((u, l)):
                if c is not None:
                    y = cy * 2 + half
                    px[y * w + cx] = (c[0], c[1], c[2], 255)
    write_png(path, px, w, h, scale)


def main():
    src, dst_svg = sys.argv[1], sys.argv[2]
    dst_png = sys.argv[3] if len(sys.argv) > 3 else ""
    scale = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    text = open(src, encoding="utf-8").read()
    rows = trim(parse_grid_v2(text))
    if not rows:
        sys.exit("empty grid")
    svg = to_svg(rows)
    open(dst_svg, "w").write(svg)
    if dst_png and dst_png != "-":
        to_png(rows, dst_png, scale)
    w_cells = max(len(r) for r in rows)
    print(f"{src}: {w_cells}x{len(rows)} cells -> {dst_svg} ({len(svg)}B)")


if __name__ == "__main__":
    main()
