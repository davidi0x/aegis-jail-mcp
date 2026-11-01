#!/usr/bin/env python3
"""Render a recorded terminal session (record.py JSON) to PNG frames -> mp4 / gif via ffmpeg.

Usage: render.py REC.json OUTDIR [fps] [speedup]
"""
import json, subprocess, sys, os
import pyte
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf"
BOLD = "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf"
FS = 17
BG, FG = (13, 17, 23), (201, 209, 217)
BAR = (22, 27, 34)
PAL = {"black": (72, 79, 88), "red": (255, 123, 114), "green": (63, 185, 80), "brown": (210, 153, 34), "blue": (88, 166, 255),
       "magenta": (188, 140, 255), "cyan": (57, 197, 207), "white": (201, 209, 217), "default": None}


def color(c, default):
    if c in PAL:
        return PAL[c] or default
    if isinstance(c, str) and len(c) == 6:
        try:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return default


def main(rec, outdir, fps=15, speed=1.0):
    d = json.load(open(rec))
    rows, cols, ev = d["rows"], d["cols"], d["events"]
    f, fb = ImageFont.truetype(FONT, FS), ImageFont.truetype(BOLD, FS)
    cw = round(f.getlength("M"))
    ch = int(FS * 1.32)
    pad, bar = 22, 44
    W, H = cols * cw + 2 * pad, rows * ch + 2 * pad + bar
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):
        if old.endswith(".png"):
            os.remove(os.path.join(outdir, old))
    scr = pyte.Screen(cols, rows)
    st = pyte.ByteStream(scr)
    total = ev[-1][0] / speed + 1.5
    n, i = int(total * fps), 0
    last = None
    for k in range(n):
        t = k / fps * speed
        while i < len(ev) and ev[i][0] <= t:
            st.feed(ev[i][1].encode()); i += 1
        sig = (i, int(t * 2) % 2 if True else 0)
        if sig == last:
            os.link(os.path.join(outdir, f"f{k-1:05d}.png"), os.path.join(outdir, f"f{k:05d}.png")) if os.path.exists(os.path.join(outdir, f"f{k-1:05d}.png")) else None
            continue
        last = sig
        im = Image.new("RGB", (W, H), BG)
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, 0, W, bar], fill=BAR)
        for j, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            dr.ellipse([20 + j * 26, 14, 36 + j * 26, 30], fill=c)
        title = "~/shop — aegis"
        dr.text((W / 2 - f.getlength(title) / 2, 12), title, font=f, fill=(139, 148, 158))
        for y in range(rows):
            line = scr.buffer[y]
            for x in range(cols):
                c = line[x]
                if c.data == " " and c.bg == "default" and not c.reverse:
                    continue
                fg, bg = color(c.fg, FG), color(c.bg, None)
                if c.reverse:
                    fg, bg = (bg or BG), (fg or FG)
                px, py = pad + x * cw, bar + pad + y * ch
                if bg:
                    dr.rectangle([px, py, px + cw, py + ch], fill=bg)
                if c.data != " ":
                    dr.text((px, py), c.data, font=fb if c.bold else f, fill=fg)
        if int(t * 2) % 2 == 0:
            cx, cy = scr.cursor.x, scr.cursor.y
            dr.rectangle([pad + cx * cw, bar + pad + cy * ch + 2, pad + cx * cw + cw - 2, bar + pad + cy * ch + ch - 2], fill=(201, 209, 217))
        im.save(os.path.join(outdir, f"f{k:05d}.png"), optimize=False, compress_level=1)
    print("frames", n, "size", W, H)
    return n


if __name__ == "__main__":
    a = sys.argv
    main(a[1], a[2], int(a[3]) if len(a) > 3 else 15, float(a[4]) if len(a) > 4 else 1.0)
