"""`aegis scan`: look for what could hijack or abuse an AI agent, *before* it runs.

Point it at a repository you are about to give an agent, or at a skill, plugin
or MCP server you are about to install. Nothing is executed. It reports:

* prompt-injection text (instructions aimed at AI, hidden HTML comments,
  "ignore previous instructions", tag-smuggled / zero-width / bidi text),
* things that run automatically on your machine: Claude Code / Cursor hooks,
  MCP server definitions, editor tasks that run on folder open, direnv,
  npm lifecycle scripts, git hooks, CI workflows with risky triggers,
* download-and-execute and obfuscated payloads (curl | sh, base64 | sh,
  eval(atob(...)), exec(base64...)),
* committed credentials, and symlinks that point outside the project.

Findings are heuristics with a severity; read them in context.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aegis_jail import secretscan, textsafe

TEXT_EXT = {".md", ".mdx", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".py", ".js", ".mjs", ".cjs",
            ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".rb", ".go", ".rs", ".java",
            ".html", ".htm", ".xml", ".cfg", ".ini", ".env", ".mdc", ".prompt", ""}
PROSE_EXT = {".md", ".mdx", ".txt", ".rst", ".html", ".htm", ".mdc", ".prompt", ".json", ".yaml", ".yml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".tox"}
SEVERITY = {"high": 3, "medium": 2, "info": 1}


@dataclass
class Finding:
    severity: str
    path: str
    line: int
    what: str
    detail: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


_EXEC = [
    (r"(curl|wget)\b[^\n|;]{0,300}\|\s*(sudo\s+)?(ba|z|da)?sh\b", "high", "download piped into a shell"),
    (r"(iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|]{0,300}\|\s*(iex|invoke-expression)", "high",
     "download piped into PowerShell"),
    (r"base64\s+(-d|--decode)[^\n]{0,120}\|\s*(ba|z)?sh", "high", "base64-decoded shell payload"),
    (r"eval\s*\(\s*(atob|Buffer\.from)\s*\(", "high", "eval of decoded data"),
    (r"exec\s*\(\s*(base64\.b64decode|codecs\.decode|bytes\.fromhex|__import__\(['\"]base64)", "high",
     "exec of decoded data"),
    (r"\bnc\s+(-e|-c)\b|/dev/tcp/\d", "high", "reverse shell pattern"),
    (r"https?://\d{1,3}(\.\d{1,3}){3}(:\d+)?/", "medium", "URL with a raw IP address"),
    (r"[A-Za-z0-9+/]{400,}={0,2}", "medium", "large base64 blob"),
    (r"(ngrok\.io|webhook\.site|requestbin|pipedream\.net|interact\.sh|burpcollaborator|oast\.)", "medium",
     "known data-collection endpoint"),
]
_EXEC_RE = [(re.compile(p, re.I), sev, what) for p, sev, what in _EXEC]
_AI_COMMENT = re.compile(r"<!--(.{0,2000}?)-->", re.S)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan_text(rel: str, text: str, out: list[Finding]) -> None:
    inv = textsafe.invisible_chars(text)
    if inv:
        hidden = textsafe.decode_tags(text)
        kinds = sorted({d for _, d in inv})
        out.append(Finding("high" if hidden or any("BIDI" in k for k in kinds) else "medium", rel,
                           _line_of(text, inv[0][0]), f"{len(inv)} invisible character(s): {', '.join(kinds)}",
                           f"hidden text: {hidden[:120]!r}" if hidden else ""))
    for m in _AI_COMMENT.finditer(text):
        marks = textsafe.injection_markers(m.group(1))
        if marks:
            out.append(Finding("high", rel, _line_of(text, m.start()), "hidden HTML comment aimed at AI agents",
                               "; ".join(marks)))
    prose = PurePosixPath(rel).suffix.lower() in PROSE_EXT or "/" not in rel and "." not in PurePosixPath(rel).name
    marks = textsafe.injection_markers(_AI_COMMENT.sub("", text)) if prose and len(text) < 2_000_000 else []
    for mk in marks:
        if mk.startswith("hidden tag-encoded") or mk in ("pipe-to-shell", "obfuscated shell"):
            continue  # reported separately (invisible text / with a line number)
        # Visible text is seen by humans too; hidden variants above are rated high.
        out.append(Finding("medium", rel, 0, f"possible prompt injection: {mk}"))
    for rx, sev, what in _EXEC_RE:
        m = rx.search(text)
        if m:
            out.append(Finding(sev, rel, _line_of(text, m.start()), what, m.group(0)[:120]))
    sec = [s for s in secretscan.find_secrets(text) if not s.startswith("Aegis")]
    if sec:
        out.append(Finding("high", rel, 0, "committed credential(s)", ", ".join(sec)))


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _autorun(root: Path, rel: str, p: Path, out: list[Finding]) -> None:
    name = p.name
    posix = PurePosixPath(rel)
    if rel.endswith(".claude/settings.json") or rel.endswith(".claude/settings.local.json") or name == "hooks.json":
        data = _json(p) or {}
        hooks = data.get("hooks") or {}
        for event, entries in (hooks.items() if isinstance(hooks, dict) else []):
            for e in entries or []:
                for h in (e.get("hooks") or []) if isinstance(e, dict) else []:
                    if isinstance(h, dict) and h.get("command"):
                        out.append(Finding("high", rel, 0, f"agent hook runs a command on {event}", str(h["command"])[:160]))
        if isinstance(data.get("permissions"), dict) and data["permissions"].get("allow"):
            out.append(Finding("medium", rel, 0, "pre-approves agent permissions",
                               ", ".join(map(str, data["permissions"]["allow"]))[:160]))
    if name in (".mcp.json", "mcp.json") or rel.endswith(".cursor/mcp.json") or rel.endswith(".vscode/mcp.json"):
        data = _json(p) or {}
        servers = data.get("mcpServers") or data.get("servers") or {}
        for sname, cfg in (servers.items() if isinstance(servers, dict) else []):
            cmd = " ".join([str((cfg or {}).get("command", ""))] + [str(a) for a in (cfg or {}).get("args", [])])
            out.append(Finding("high", rel, 0, f"defines MCP server '{sname}' (starts automatically in some clients)",
                               cmd.strip()[:160] or str((cfg or {}).get("url", ""))[:160]))
    if rel.endswith(".vscode/tasks.json"):
        if "folderOpen" in p.read_text(encoding="utf-8", errors="replace"):
            out.append(Finding("high", rel, 0, "editor task runs automatically when the folder is opened"))
    if name == ".envrc":
        out.append(Finding("medium", rel, 0, "direnv script runs when you cd into the project"))
    if name == "package.json":
        scripts = (_json(p) or {}).get("scripts") or {}
        for k in ("preinstall", "install", "postinstall", "prepare", "prepublish"):
            if k in scripts:
                out.append(Finding("medium", rel, 0, f"npm lifecycle script '{k}' runs on install", str(scripts[k])[:160]))
    if len(posix.parts) >= 2 and posix.parts[0] == ".github" and posix.parts[1] == "workflows":
        text = p.read_text(encoding="utf-8", errors="replace")
        if "pull_request_target" in text:
            out.append(Finding("high", rel, 0, "workflow uses pull_request_target (secrets exposed to fork PRs)"))
    if posix.parts and posix.parts[0] in (".husky", ".githooks"):
        out.append(Finding("info", rel, 0, "git hook script"))
    if name == "SKILL.md" or name == "plugin.json":
        out.append(Finding("info", rel, 0, "agent skill / plugin definition - its instructions steer the agent"))


def scan(root: Path, max_files: int = 20000) -> list[Finding]:
    root = root.resolve()
    out: list[Finding] = []
    count = 0
    targets = [root] if root.is_file() else None
    walker = ([(root.parent, [], [root.name])] if targets else os.walk(root))
    base = root.parent if targets else root
    for dirpath, dirnames, filenames in walker:
        for d in list(dirnames):
            dp = Path(dirpath) / d
            if dp.is_symlink():
                try:
                    target = dp.resolve()
                    if not target.is_relative_to(base):
                        out.append(Finding("high", dp.relative_to(base).as_posix(), 0,
                                           "symlink points outside the project", str(target)))
                except OSError:
                    pass
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not (Path(dirpath) / d).is_symlink()]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(base).as_posix()
            count += 1
            if count > max_files:
                out.append(Finding("info", ".", 0, f"stopped after {max_files} files"))
                return _sorted(out)
            if p.is_symlink():
                try:
                    target = p.resolve()
                    if not target.is_relative_to(base):
                        out.append(Finding("high", rel, 0, "symlink points outside the project", str(target)))
                except OSError:
                    pass
                continue
            try:
                if p.stat().st_size > 5_000_000:
                    continue
            except OSError:
                continue
            if secretscan.is_secret_filename(rel):
                out.append(Finding("medium", rel, 0, "credential-like file committed to the project"))
            _autorun(base, rel, p, out)
            if p.suffix.lower() in TEXT_EXT or fn.startswith("."):
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if b"\0" in data[:4096]:
                    continue
                _scan_text(rel, data.decode("utf-8", "replace"), out)
    return _sorted(out)


def _sorted(out: list[Finding]) -> list[Finding]:
    seen = set()
    uniq = []
    for f in out:
        k = (f.severity, f.path, f.what)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return sorted(uniq, key=lambda f: (-SEVERITY[f.severity], f.path, f.line))


def render(findings: list[Finding], root: Path) -> str:
    if not findings:
        return f"aegis scan: nothing suspicious found in {root}"
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITY}
    lines = [f"aegis scan of {root}: {counts['high']} high, {counts['medium']} medium, {counts['info']} info", ""]
    for f in findings:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"[{f.severity.upper():6s}] {loc}: {f.what}" + (f"\n          {f.detail}" if f.detail else ""))
    return textsafe.for_terminal("\n".join(lines))
