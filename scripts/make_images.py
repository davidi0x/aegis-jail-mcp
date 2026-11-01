#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the README images in docs/images/ (SVG, plus a PNG social preview).

Terminal screenshots are rendered from *real* command output (captured with
`aegis demo`, `aegis optimize`, `aegis scan`), so the pictures never drift from
what the program prints. Re-run after changing output:

    python scripts/make_images.py --demo demo.txt --optimize optimize.txt --scan scan.txt
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"

BG, PANEL, BORDER = "#0d1117", "#161b22", "#30363d"
TEXT, DIM = "#e6edf3", "#8b949e"
BLUE, GREEN, RED, YELLOW, PURPLE, CYAN = "#58a6ff", "#3fb950", "#f85149", "#d29922", "#bc8cff", "#39c5cf"
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def esc(s: str) -> str:
    return html.escape(s, quote=False)


# --------------------------------------------------------------------------- terminals
def colour(line: str) -> list[tuple[str, str]]:
    """Split a line of real output into coloured segments."""
    if line.startswith("!g "):
        return [(line[3:], GREEN)]
    if line.startswith("$ "):
        return [("$ ", GREEN), (line[2:], TEXT)]
    if line.strip().startswith("(the 'keys'"):
        return [(line, YELLOW)]
    if line.strip().startswith("..."):
        return [(line, DIM)]
    if line.strip().startswith("TRIPWIRE"):
        return [(line, RED)]
    if re.match(r"^\s*\[(HIGH)", line):
        return [(line[:8], RED), (line[8:], TEXT)]
    if re.match(r"^\s*\[(MEDIUM)", line):
        return [(line[:8], YELLOW), (line[8:], TEXT)]
    m = re.match(r"^(\[aegis\] run \d+/\d+: )(.*?)(PASS|FAIL.*)$", line)
    if m:
        return [(m.group(1), DIM), (m.group(2), TEXT), (m.group(3), GREEN if m.group(3) == "PASS" else RED)]
    if line.startswith("[aegis]"):
        return [(line, DIM)]
    if re.match(r"^\d\) ", line):
        return [(line, BLUE)]
    if "checks passed" in line or "result: tests PASS" in line.strip():
        return [(line, GREEN)]
    if "blocked network" in line:
        return [(line, YELLOW)]
    if line.strip().startswith("[agent]"):
        body = line.strip()
        col = YELLOW if ("DECOY" in body.upper() or "BEGIN OPENSSH" in body or "[default]" in body) else (
            RED if ("failed" in body or "Read-only" in body or "FileNotFound" in body) else TEXT)
        return [("   " + body, CYAN if col == TEXT else col)]
    if line.startswith("Secrets stayed hidden") or "Applied" in line:
        return [(line, GREEN)]
    if line.startswith("The task passed") or line.startswith("Saved verified"):
        return [(line, GREEN)]
    if line.startswith("(") or line.startswith("   your real project") or line.startswith("The project has") \
            or line.startswith("The (scripted") or line.startswith("~/.ssh"):
        return [(line, DIM)]
    return [(line, TEXT)]


def terminal(lines: list[str], title: str, name: str, max_cols: int = 108) -> None:
    lines = [ln.rstrip() if len(ln.rstrip()) <= max_cols else ln.rstrip()[:max_cols - 1] + "…" for ln in lines]
    cw, lh, pad_x, top = 8.05, 19.5, 26, 54
    cols = max((len(ln) for ln in lines), default=40)
    w = int(cols * cw + pad_x * 2 + 6)
    h = int(top + len(lines) * lh + 26)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
           f'aria-label="{esc(title)}">',
           f'<rect width="{w}" height="{h}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
           f'<rect width="{w}" height="38" rx="10" fill="{PANEL}"/><rect y="28" width="{w}" height="10" fill="{PANEL}"/>',
           f'<line x1="0" y1="38" x2="{w}" y2="38" stroke="{BORDER}"/>',
           '<circle cx="22" cy="19" r="6" fill="#ff5f56"/><circle cx="42" cy="19" r="6" fill="#ffbd2e"/>'
           '<circle cx="62" cy="19" r="6" fill="#27c93f"/>',
           f'<text x="{w // 2}" y="24" fill="{DIM}" font-family="{SANS}" font-size="13" text-anchor="middle">'
           f'{esc(title)}</text>']
    y = top + 14
    for ln in lines:
        segs = "".join(f'<tspan fill="{c}">{esc(t)}</tspan>' for t, c in colour(ln))
        out.append(f'<text x="{pad_x}" y="{y:.1f}" font-family="{FONT}" font-size="13.5" xml:space="preserve">{segs}</text>')
        y += lh
    out.append("</svg>")
    (OUT / name).write_text("\n".join(out), encoding="utf-8")


def clean(text: str) -> list[str]:
    """Drop machine-specific noise from captured output."""
    out = []
    for ln in text.splitlines():
        if ln.startswith(("Demo files:", "Try next:", "Shell cwd")) or set(ln.strip()) == {"="}:
            continue
        ln = re.sub(r"/tmp/[\w./-]*?/scratchpad/shop", "~/shop", ln)
        ln = re.sub(r"/tmp/aegis-demo-\w+/shop", "~/shop", ln)
        ln = ln.replace("/root/", "~/").replace("'/root", "'~")
        ln = re.sub(r"FileNotFoundError: \[Errno 2\] No such file or directory: '[^']*'", "FileNotFoundError: not found", ln)
        ln = ln.replace("OSError: [Errno 30] Read-only file system: '~/.bashrc_aegis_demo'", "Read-only file system")
        ln = ln.replace("-----BEGIN OPENSSH PRIVATE KEY-----", "-----BEGIN OPENSSH")  # keep scanners quiet
        ln = ln.replace("request carries credentials: Aegis decoy credential, private key", "request carries a decoy key")
        ln = ln.replace("decoy credentials appeared in the program's output", "decoy keys appeared in the output")
        ln = re.sub(r"\\n.*$", "…", ln) if "[agent] read" in ln and "\\n" in ln else ln
        out.append(ln)
    while out and not out[-1].strip():
        out.pop()
    return out


# --------------------------------------------------------------------------- shield
SHIELD = ('<path d="M0,-52 L44,-38 L44,6 C44,30 24,46 0,58 C-24,46 -44,30 -44,6 L-44,-38 Z" fill="#1f6feb" '
          'stroke="#58a6ff" stroke-width="3"/><circle cx="0" cy="-8" r="11" fill="#0d1117"/>'
          '<rect x="-5" y="-4" width="10" height="26" rx="2" fill="#0d1117"/>')


def banner(width: int = 1280, height: int = 400, social: bool = False) -> str:
    cx = width // 2
    chips = [("Linux · macOS · Windows", BLUE), ("MCP jail", PURPLE), ("0 dependencies", GREEN), ("AGPL-3.0", YELLOW)]
    chip_svg, x = [], cx - 400
    for label, col in chips:
        wlab = len(label) * 8.6 + 34
        chip_svg.append(f'<rect x="{x:.0f}" y="{height // 2 + 122}" width="{wlab:.0f}" height="34" rx="17" fill="none" '
                        f'stroke="{col}" stroke-opacity=".7"/><text x="{x + wlab / 2:.0f}" y="{height // 2 + 144}" fill="{col}" '
                        f'font-family="{SANS}" font-size="15" text-anchor="middle">{esc(label)}</text>')
        x += wlab + 14
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Aegis Jail MCP - give AI agents a task, not your whole computer">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0d1117"/><stop offset="1" stop-color="#10213f"/></linearGradient>
<radialGradient id="glow" cx=".5" cy=".38" r=".5"><stop offset="0" stop-color="#1f6feb" stop-opacity=".35"/><stop offset="1" stop-color="#1f6feb" stop-opacity="0"/></radialGradient>
</defs>
<rect width="{width}" height="{height}" fill="url(#bg)"/><rect width="{width}" height="{height}" fill="url(#glow)"/>
<g stroke="#58a6ff" stroke-opacity=".07">{"".join(f'<line x1="{i}" y1="0" x2="{i}" y2="{height}"/>' for i in range(0, width, 64))}{"".join(f'<line x1="0" y1="{j}" x2="{width}" y2="{j}"/>' for j in range(0, height, 64))}</g>
<g transform="translate({cx - 360},{height // 2 - 34}) scale(1.35)">{SHIELD}</g>
<text x="{cx - 270}" y="{height // 2 - 8}" fill="#ffffff" font-family="{SANS}" font-size="80" font-weight="800" letter-spacing="-2">Aegis <tspan fill="#58a6ff">Jail MCP</tspan></text>
<text x="{cx - 268}" y="{height // 2 + 44}" fill="#c9d1d9" font-family="{SANS}" font-size="28">Give AI agents a task, not your whole computer.</text>
<text x="{cx - 268}" y="{height // 2 + 82}" fill="{DIM}" font-family="{SANS}" font-size="19">A least-privilege sandbox for coding agents and MCP servers.</text>
{"".join(chip_svg)}
</svg>'''


# --------------------------------------------------------------------------- diagrams
def box(x, y, w, h, fill, stroke, rx=12):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'


def txt(x, y, s, size=16, fill=TEXT, anchor="start", weight="400", font=SANS):
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}">{esc(s)}</text>')


def arrow(x1, y1, x2, y2, col=BLUE, dash=False):
    d = ' stroke-dasharray="6 5"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="2.5"{d} marker-end="url(#a{col[1:]})"/>')


def defs(*cols):
    m = "".join(f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in cols)
    return f"<defs>{m}</defs>"


def architecture() -> str:
    w, h = 1100, 520
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
         f'aria-label="Aegis architecture: an untrusted agent runs inside an OS sandbox between it and your machine">',
         defs(BLUE, RED, GREEN), f'<rect width="{w}" height="{h}" rx="14" fill="{BG}" stroke="{BORDER}"/>',
         txt(w // 2, 44, "What sits between an AI agent and your machine", 24, "#fff", "middle", "700")]
    # left: untrusted
    s += [box(40, 90, 230, 330, "#2d1417", RED), txt(155, 126, "UNTRUSTED", 14, RED, "middle", "700"),
          txt(155, 156, "AI coding agent", 17, TEXT, "middle", "600"),
          txt(155, 184, "Claude Code · Codex", 14, DIM, "middle"), txt(155, 204, "Gemini · Aider", 14, DIM, "middle"),
          txt(155, 246, "MCP server", 17, TEXT, "middle", "600"), txt(155, 272, "npx / uvx / any binary", 14, DIM, "middle"),
          txt(155, 314, "Scripts & dependencies", 17, TEXT, "middle", "600"),
          txt(155, 340, "npm install · pytest", 14, DIM, "middle"),
          txt(155, 388, "can be steered by a README,", 13, RED, "middle"), txt(155, 406, "an issue or a web page", 13, RED, "middle")]
    # middle: aegis
    s += [box(330, 70, 440, 370, "#0e2147", BLUE, 16), txt(550, 104, "AEGIS JAIL MCP", 16, BLUE, "middle", "800")]
    layers = [("OS sandbox", "bubblewrap · Seatbelt · AppContainer", BLUE),
              ("Syscall filter", "seccomp blocklist (Linux)", BLUE),
              ("Working copy", "agent edits a copy, you review the diff", GREEN),
              ("Filtering proxy", "allowed hosts only · ports · TLS SNI · DLP", GREEN),
              ("Decoys & tripwires", "fake keys expose a hijacked agent", YELLOW),
              ("MCP firewall", "pinning · poisoning scan · secret egress", PURPLE)]
    y = 126
    for name, sub, col in layers:
        s += [box(354, y, 392, 46, "#0d1117", col, 8), f'<rect x="354" y="{y}" width="6" height="46" rx="3" fill="{col}"/>',
              txt(374, y + 20, name, 15, "#fff", "start", "700"), txt(374, y + 38, sub, 12.5, DIM)]
        y += 52
    # right: machine
    s += [box(815, 90, 255, 330, "#0f2a1a", GREEN), txt(942, 126, "YOUR MACHINE", 14, GREEN, "middle", "700")]
    hidden = ["~/.ssh  ~/.aws  ~/.kube", "other projects & dotfiles", "tokens in env variables",
              ".env / keys in the project", "Docker · ssh-agent · keyring", "clipboard · keychain (macOS)"]
    y = 156
    for item in hidden:
        s += [txt(837, y, "✕", 15, RED, "start", "700"), txt(861, y, item, 13.5, TEXT)]
        y += 28
    s += [txt(837, y + 14, "✓", 15, GREEN, "start", "700"), txt(861, y + 14, "a copy of the project", 13.5, "#fff", "start", "600"),
          txt(837, y + 42, "✓", 15, GREEN, "start", "700"), txt(861, y + 42, "only the hosts you allow", 13.5, "#fff", "start", "600")]
    s += [arrow(272, 255, 326, 255, RED), arrow(772, 255, 811, 255, GREEN, True)]
    s += [txt(w // 2, 488, "The boundary is enforced by the operating system and applies to every child process.",
              15, DIM, "middle")]
    s.append("</svg>")
    return "\n".join(s)


def pipeline() -> str:
    w, h = 1100, 300
    steps = [("Project", "your repo", BLUE), ("Copy", "secrets left out", BLUE), ("Setup", "npm ci ...", GREEN),
             ("Agent", "does the task", YELLOW), ("Verify", "npm test", GREEN), ("Report", "diff + alerts", PURPLE),
             ("You decide", "apply / discard", BLUE)]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
         f'aria-label="How an Aegis run works: copy, setup, agent, verify, report, you decide">',
         defs(BLUE), f'<rect width="{w}" height="{h}" rx="14" fill="{BG}" stroke="{BORDER}"/>',
         txt(w // 2, 42, "How a run works", 24, "#fff", "middle", "700")]
    bw, gap, x0 = 124, 20, 30
    for i, (a, b, col) in enumerate(steps):
        x = x0 + i * (bw + gap)
        s += [box(x, 100, bw, 84, PANEL, col), txt(x + bw / 2, 134, a, 17, "#fff", "middle", "700"),
              txt(x + bw / 2, 158, b, 13, DIM, "middle")]
        if i < len(steps) - 1:
            s.append(arrow(x + bw + 2, 142, x + bw + gap - 2, 142))
    sx = x0 + 2 * (bw + gap) - 10
    ex = x0 + 5 * (bw + gap) - gap + 10
    s += [f'<rect x="{sx}" y="84" width="{ex - sx}" height="116" rx="16" fill="none" stroke="{BLUE}" stroke-width="2" stroke-dasharray="8 6"/>',
          txt((sx + ex) / 2, 78, "inside the OS sandbox · no home dir · no keys · network off or allowlisted", 14, BLUE, "middle", "600"),
          txt(w // 2, 242, "Nothing reaches your real project until you run  aegis apply.", 16, TEXT, "middle", "600"),
          txt(w // 2, 270, "Changes that could run code outside the sandbox (hooks, CI, MCP config, scripts) need an explicit yes.",
              14, DIM, "middle"), "</svg>"]
    return "\n".join(s)


def mcp_jail() -> str:
    w, h = 1100, 430
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
         f'aria-label="aegis mcp-jail sits between your MCP client and an MCP server">',
         defs(BLUE, PURPLE), f'<rect width="{w}" height="{h}" rx="14" fill="{BG}" stroke="{BORDER}"/>',
         txt(w // 2, 42, "aegis mcp-jail: run any MCP server without trusting it", 24, "#fff", "middle", "700")]
    s += [box(30, 110, 190, 220, PANEL, BLUE), txt(125, 150, "MCP client", 18, "#fff", "middle", "700"),
          txt(125, 180, "Claude Code", 14, DIM, "middle"), txt(125, 202, "Claude Desktop", 14, DIM, "middle"),
          txt(125, 224, "Cursor · VS Code", 14, DIM, "middle"), txt(125, 262, "your model sees only", 13, TEXT, "middle"),
          txt(125, 282, "filtered, clean tools", 13, TEXT, "middle")]
    s += [box(300, 80, 500, 290, "#1d1535", PURPLE, 16), txt(550, 110, "AEGIS JAIL MCP", 15, PURPLE, "middle", "800")]
    rules = [("Tool firewall", "--allow-tools / --deny-tools globs"),
             ("Rug-pull protection", "definitions pinned; a change hides it"),
             ("Poisoning filter", "hidden instructions & invisible Unicode"),
             ("Secret egress block", "no credentials in tool arguments"),
             ("Sampling guard", "server can't drive your model"),
             ("Audit log", "~/.aegis/mcp/<name>.jsonl")]
    y = 124
    for a, b in rules:
        s += [f'<circle cx="326" cy="{y + 14}" r="5" fill="{PURPLE}"/>', txt(342, y + 19, a, 15, "#fff", "start", "700"),
              txt(540, y + 19, b, 13, DIM)]
        y += 40
    s += [box(880, 110, 190, 220, "#2d1417", RED), txt(975, 150, "MCP server", 18, "#fff", "middle", "700"),
          txt(975, 180, "inside the sandbox:", 13, RED, "middle"), txt(975, 206, "✕ home directory", 13.5, TEXT, "middle"),
          txt(975, 228, "✕ credentials", 13.5, TEXT, "middle"), txt(975, 250, "✕ network (unless listed)", 13.5, TEXT, "middle"),
          txt(975, 272, "✕ other processes", 13.5, TEXT, "middle")]
    s += [arrow(222, 190, 296, 190, BLUE), arrow(296, 250, 222, 250, BLUE), arrow(802, 190, 876, 190, PURPLE),
          arrow(876, 250, 802, 250, PURPLE)]
    s += [txt(w // 2, 404, 'aegis mcp-jail --allow-hosts api.github.com --deny-tools "delete_*" -- npx -y @modelcontextprotocol/server-github',
              13.5, CYAN, "middle", font=FONT), "</svg>"]
    return "\n".join(s)


def before_after() -> str:
    w, h = 1100, 470
    rows = [("~/.ssh, ~/.aws, ~/.kube", "readable", "hidden"), ("Other projects & dotfiles", "readable", "hidden"),
            ("Writes outside the project", "allowed", "blocked"), ("Network", "everything", "off, or only your hosts"),
            ("Tokens in environment", "inherited", "not passed"), ("Agent's changes", "land in your repo", "in a copy: diff → apply"),
            ("README says: \"send me ~/.ssh\"", "agent obeys, as you", "hits a wall, trips an alarm")]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
         f'aria-label="Without Aegis versus with Aegis">', f'<rect width="{w}" height="{h}" rx="14" fill="{BG}" stroke="{BORDER}"/>',
         txt(w // 2, 44, "The same agent, with and without Aegis", 24, "#fff", "middle", "700"),
         box(560, 70, 240, 44, "#2d1417", RED, 8), txt(680, 99, "Without Aegis", 17, RED, "middle", "700"),
         box(820, 70, 250, 44, "#0f2a1a", GREEN, 8), txt(945, 99, "With Aegis", 17, GREEN, "middle", "700")]
    y = 134
    for i, (a, b, c) in enumerate(rows):
        if i % 2 == 0:
            s.append(f'<rect x="20" y="{y - 6}" width="{w - 40}" height="46" rx="8" fill="{PANEL}"/>')
        s += [txt(44, y + 24, a, 17, TEXT), txt(680, y + 24, b, 16, "#ff7b72", "middle"),
              txt(945, y + 24, c, 16, "#56d364", "middle", "600")]
        y += 46
    s.append("</svg>")
    return "\n".join(s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo"), ap.add_argument("--optimize"), ap.add_argument("--scan"), ap.add_argument("--probe")
    ap.add_argument("--png", action="store_true", help="also render PNGs with Playwright")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "banner.svg").write_text(banner(), encoding="utf-8")
    (OUT / "social-preview.svg").write_text(banner(1280, 640), encoding="utf-8")
    (OUT / "architecture.svg").write_text(architecture(), encoding="utf-8")
    (OUT / "pipeline.svg").write_text(pipeline(), encoding="utf-8")
    (OUT / "mcp-jail.svg").write_text(mcp_jail(), encoding="utf-8")
    (OUT / "before-after.svg").write_text(before_after(), encoding="utf-8")
    if a.demo:
        body = clean(Path(a.demo).read_text(encoding="utf-8"))
        terminal(["$ aegis demo", ""] + body[1:], "aegis demo: a prompt-injected agent, contained", "demo.svg")
    if a.optimize:
        body = [ln for ln in Path(a.optimize).read_text(encoding="utf-8").splitlines()
                if ln.startswith("[aegis] run") or ln.startswith("**The task") or ln.startswith("Saved")]
        body = [re.sub(r"^\*\*|\*\*$", "", ln) for ln in body]
        body = [re.sub(r"(/[\w./-]*)(/\.aegis/)", r"~/shop\2", ln) for ln in body]
        long = [ln for ln in body if ln.startswith("The task passed")]
        short = ["!g The task passed its tests WITHOUT: the home directory, ~/.ssh, ~/.aws, ~/.config/gcloud,",
                 "!g internet (setup and task) and 15 credential-like environment variables."] if long else []
        body = [ln for ln in body if not ln.startswith("The task passed")][:6] + [""] + short
        body = [ln.replace("[aegis] run", "[aegis] run").replace("without home-read, secret:ssh, secret:aws, secret:gcloud, net-setup-any, net-task-any, env-all-ish",
                                                               "without all of the above") for ln in body]
        terminal(["$ aegis optimize --start baseline", ""] + body + ["", "!g Saved verified profile to .aegis/profiles/verified.json"],
                 "aegis optimize: find the smallest permissions that still pass", "optimize.svg")
    if a.scan:
        body = [ln for ln in Path(a.scan).read_text(encoding="utf-8").splitlines() if ln.strip() and "Shell cwd" not in ln]
        body[0] = re.sub(r"of .*: ", "of ./untrusted-repo: ", body[0])
        body = [ln.replace("/root/", "~/") for ln in body]
        terminal(["$ aegis scan ./untrusted-repo", ""] + body[:21] + ["        ... and 3 more findings"],
                 "aegis scan: what could hijack an agent in this repo?", "scan.svg")
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))
    if a.png:
        import shutil
        import subprocess
        import tempfile
        js = """const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();
        const pg=await b.newPage({viewport:{width:1280,height:640}});
        await pg.goto('file://'+process.argv[2]);await pg.screenshot({path:process.argv[3]});await b.close();})();"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
        subprocess.run(["node", f.name, str(OUT / "social-preview.svg"), str(OUT / "social-preview.png")], check=True)
        print("wrote social-preview.png (upload it in Settings -> Social preview)")


if __name__ == "__main__":
    main()
