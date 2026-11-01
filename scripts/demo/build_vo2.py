#!/usr/bin/env python3
"""Retime a recorded session to a voice-over, scene by scene, and mix the final video with music.

Usage: build_vo2.py SPEC.json LANG REC.json AUDIO_DIR MUSIC.mp3 OUT.mp4 [title-line]
SPEC.json: {"scenes": [{"anchor": <orig time the scene's visuals begin>}, ...]}  (n scenes; outro = n-th clip on the end card)
AUDIO_DIR holds s1.mp3..s{n+1}.mp3. Each scene's narration starts together with its visuals; if the previous
narration is still running, the real frames are held (not altered) until it ends.
"""
import json, os, shutil, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

spec, lang, rec, adir, music, out = sys.argv[1:7]
title = sys.argv[7] if len(sys.argv) > 7 else "Give AI agents a task, not your whole computer."
scenes = json.load(open(spec))["scenes"]
n = len(scenes)
tmp = os.path.join(os.path.dirname(os.path.abspath(out)), f"_vo2_{lang}")
shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
dur = [float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"{adir}/s{i}.mp3"])) for i in range(1, n + 2)]

gaps, G, prev_end, starts = [], 0.0, -1.0, []
for i, sc in enumerate(scenes):
    a = sc["anchor"]
    start = max(a + G, prev_end + 0.35)
    if start > a + G + 1e-6:
        gaps.append((a - 0.02, start - (a + G))); G = start - a
    starts.append(start); prev_end = start + dur[i]
d = json.load(open(rec))
ev = [[t + sum(g for gt, g in gaps if t > gt), x] for t, x in d["events"]]
if prev_end + 0.8 > ev[-1][0]:
    ev.append([prev_end + 0.8, ""])
json.dump({"rows": d["rows"], "cols": d["cols"], "events": ev}, open(f"{tmp}/rec.json", "w"))
here = os.path.dirname(os.path.abspath(__file__))
subprocess.check_call([sys.executable, f"{here}/render.py", f"{tmp}/rec.json", f"{tmp}/frames", "15", "1.0"])
nframes = len([f for f in os.listdir(f"{tmp}/frames") if f.endswith(".png")])
W, H = Image.open(f"{tmp}/frames/f00000.png").size

card = Image.new("RGB", (W, H), (13, 17, 23)); dr = ImageDraw.Draw(card)
F = lambda w, s: ImageFont.truetype(f"/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-{w}.ttf", s)
for txt, font, col, y in [("Aegis Jail MCP", F("Bold", 54), (230, 237, 243), H * 0.36), (title, F("Regular", 24), (139, 148, 158), H * 0.36 + 90),
                          ("github.com/davidi0x/aegis-jail-mcp", F("Regular", 24), (88, 166, 255), H * 0.36 + 150)]:
    dr.text(((W - dr.textlength(txt, font=font)) / 2, y), txt, font=font, fill=col)
card.save(f"{tmp}/card.png")
card_len = dur[n] + 1.4; vid_len = nframes / 15; total = vid_len + card_len
starts.append(vid_len + 0.3)
vf = "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p"
caps = os.environ.get("CAPTIONS")  # optional JSON list of n+1 caption strings, burned into a bar under the terminal
if caps:
    import textwrap
    texts = json.load(open(caps)); ends = [s + dur[i] for i, s in enumerate(starts)]
    vf += ",pad=iw:ih+170:0:0:color=0x0d1117"
    for i, (t, st, en) in enumerate(zip(texts, starts, ends)):
        open(f"{tmp}/cap{i}.txt", "w").write("\n".join(textwrap.wrap(t, 72)))
        vf += (f",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={tmp}/cap{i}.txt:fontsize=28:fontcolor=0xe6edf3:"
               f"x=(w-text_w)/2:y=h-150:line_spacing=8:enable='between(t,{st:.2f},{en + 0.4:.2f})'")
subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", f"{tmp}/frames/f%05d.png", "-framerate", "15", "-loop", "1", "-t", f"{card_len}", "-i", f"{tmp}/card.png",
                       "-filter_complex", vf + "[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "18", f"{tmp}/video.mp4"])
inputs, filt = [], []
for i, st in enumerate(starts):
    inputs += ["-i", f"{adir}/s{i+1}.mp3"]; ms = int(st * 1000)
    filt.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
inputs += ["-stream_loop", "-1", "-i", music]
filt.append("".join(f"[v{i}]" for i in range(n + 1)) + f"amix=inputs={n+1}:normalize=0,asplit=2[vsc][vmx]")
filt.append(f"[{n+1}:a]volume=0.20,atrim=0:{total:.2f},afade=t=in:d=1.5,afade=t=out:st={total-3:.2f}:d=3[mus]")
filt.append("[mus][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck];[duck][vmx]amix=inputs=2:normalize=0:duration=longest[a]")
subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-i", f"{tmp}/video.mp4", "-filter_complex", ";".join(filt), "-map", f"{n+2}:v", "-map", "[a]",
                       "-t", f"{total:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out])
print("built", out, round(total, 1), "s; holds:", [(round(t, 1), round(g, 1)) for t, g in gaps])
