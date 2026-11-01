#!/usr/bin/env python3
"""Retime a recorded session to a voice-over and mix the final video.

Usage: build_vo.py LANG REC.json AUDIO_DIR MUSIC.mp3 OUT.mp4 [title-line] [url]
AUDIO_DIR holds s1.mp3..s7.mp3 (s7 = outro, spoken over the end card).
The terminal frames are the real recording; only waiting time is inserted (a held frame).
"""
import json, os, subprocess, sys, shutil
from PIL import Image, ImageDraw, ImageFont

lang, rec, adir, music, out = sys.argv[1:6]
tmp = os.path.join(os.path.dirname(os.path.abspath(out)), f"_vo_{lang}")
shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
dur = [float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"{adir}/s{i}.mp3"])) for i in range(1, 8)]
d1, d2, d3, d4, d5, d6, d7 = dur

# narration start times (new timeline) and the held-frame gaps they require
s1 = 0.4
s2 = 6.2
A = max(0, s2 + d2 - 0.2 - 12.6)
s3 = s2 + d2 + 0.3
B = max(0, s3 + d3 + 0.5 - (18.9 + A))
s4 = 19.6 + A + B + 0.2
C = max(0, s4 + d4 + 0.3 - (25.25 + A + B))
s5 = 25.25 + A + B + C + 0.3
D = max(0, s5 + d5 + 0.6 - (29.5 + A + B + C))
s6 = 34.2 + A + B + C + D
gaps = [(12.4, A), (18.9, B), (21.4, C), (29.0, D)]
d = json.load(open(rec))
ev = []
for t, x in d["events"]:
    ev.append([t + sum(g for gt, g in gaps if t > gt), x])
end_t = ev[-1][0]
if s6 + d6 + 0.8 > end_t:
    ev.append([s6 + d6 + 0.8, ""])
json.dump({"rows": d["rows"], "cols": d["cols"], "events": ev}, open(f"{tmp}/rec.json", "w"))
here = os.path.dirname(os.path.abspath(__file__))
subprocess.check_call([sys.executable, f"{here}/render.py", f"{tmp}/rec.json", f"{tmp}/frames", "15", "1.0"])
sample = Image.open(f"{tmp}/frames/f00000.png"); W, H = sample.size
nframes = len([f for f in os.listdir(f"{tmp}/frames") if f.endswith(".png")])

# end card (plain, typographic; the product name + install line)
card = Image.new("RGB", (W, H), (13, 17, 23)); dr = ImageDraw.Draw(card)
F = lambda n, s: ImageFont.truetype(f"/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-{n}.ttf", s)
title = sys.argv[6] if len(sys.argv) > 6 else "Give AI agents a task, not your whole computer."
url = sys.argv[7] if len(sys.argv) > 7 else "github.com/davidi0x/aegis-jail-mcp"
for i, (txt, font, col, y) in enumerate([("Aegis Jail MCP", F("Bold", 54), (230, 237, 243), H * 0.36), (title, F("Regular", 24), (139, 148, 158), H * 0.36 + 90), (url, F("Regular", 24), (88, 166, 255), H * 0.36 + 150)]):
    w = dr.textlength(txt, font=font); dr.text(((W - w) / 2, y), txt, font=font, fill=col)
card.save(f"{tmp}/card.png")
card_len = d7 + 1.4
vid_len = nframes / 15

subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", f"{tmp}/frames/f%05d.png", "-framerate", "15", "-loop", "1", "-t", f"{card_len}", "-i", f"{tmp}/card.png",
    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "18", f"{tmp}/video.mp4"])
total = vid_len + card_len
starts = [s1, s2, s3, s4, s5, s6, vid_len + 0.3]
inputs, filt = [], []
for i, st in enumerate(starts):
    inputs += ["-i", f"{adir}/s{i+1}.mp3"]
    filt.append(f"[{i}:a]adelay={int(st*1000)}|{int(st*1000)},volume=1.0[v{i}]")
inputs += ["-stream_loop", "-1", "-i", music]
voice = "".join(f"[v{i}]" for i in range(7))
filt.append(f"{voice}amix=inputs=7:normalize=0,asplit=2[vsc][vmx]")
filt.append(f"[7:a]volume=0.20,atrim=0:{total:.2f},afade=t=in:d=1.5,afade=t=out:st={total-3:.2f}:d=3[mus]")
filt.append("[mus][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]")
filt.append("[duck][vmx]amix=inputs=2:normalize=0:duration=longest[a]")
subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-i", f"{tmp}/video.mp4", "-filter_complex", ";".join(filt), "-map", "8:v", "-map", "[a]",
    "-t", f"{total:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
print("built", out, round(total, 1), "s", "gaps", [round(g, 1) for _, g in gaps])
