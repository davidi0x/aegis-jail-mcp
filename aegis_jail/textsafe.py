# SPDX-License-Identifier: AGPL-3.0-or-later
"""Defences for text that crosses a trust boundary.

Agents, repositories and MCP servers can hide things in text:

* terminal escape sequences (OSC 52 writes your clipboard, OSC 8 fakes links,
  CSI can rewrite what you see on screen),
* invisible Unicode: "ASCII smuggling" with tag characters (U+E0000..E007F),
  zero-width characters, bidi overrides ("Trojan Source"),
* instructions aimed at AI models ("ignore previous instructions...").

`for_terminal` neutralises the first two before anything agent-controlled is
printed; `invisible_chars` and `injection_markers` power `aegis scan`, the MCP
tool firewall and the risky-change review.
"""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = {
    0x200B: "ZERO WIDTH SPACE", 0x200C: "ZERO WIDTH NON-JOINER", 0x200D: "ZERO WIDTH JOINER",
    0x2060: "WORD JOINER", 0xFEFF: "ZERO WIDTH NO-BREAK SPACE", 0x00AD: "SOFT HYPHEN",
    0x180E: "MONGOLIAN VOWEL SEPARATOR", 0x2061: "FUNCTION APPLICATION", 0x2062: "INVISIBLE TIMES",
    0x2063: "INVISIBLE SEPARATOR", 0x2064: "INVISIBLE PLUS",
}
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F, 0x061C}


def _is_tag(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F


def invisible_chars(text: str) -> list[tuple[int, str]]:
    """(offset, description) for every invisible / direction-changing / tag character."""
    out = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        if _is_tag(cp):
            out.append((i, "UNICODE TAG (ASCII smuggling)"))
        elif cp in _INVISIBLE:
            out.append((i, _INVISIBLE[cp]))
        elif cp in _BIDI:
            out.append((i, "BIDI CONTROL (Trojan Source)"))
        elif 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
            if i == 0 or not unicodedata.category(text[i - 1]).startswith("S"):
                out.append((i, "VARIATION SELECTOR (possible hidden payload)"))
    return out


def decode_tags(text: str) -> str:
    """Reveal text hidden with Unicode tag characters."""
    return "".join(chr(ord(c) - 0xE0000) for c in text if 0xE0020 <= ord(c) <= 0xE007E)


def strip_invisible(text: str) -> str:
    return "".join(c for c in text if not (_is_tag(ord(c)) or ord(c) in _INVISIBLE or ord(c) in _BIDI))


def for_terminal(text: str) -> str:
    """Make agent-controlled text safe to print: escape control chars and invisible Unicode."""
    out = []
    for ch in text:
        cp = ord(ch)
        if ch in "\n\t":
            out.append(ch)
        elif cp < 0x20 or cp == 0x7F or 0x80 <= cp <= 0x9F:
            out.append(f"\\x{cp:02x}")
        elif _is_tag(cp) or cp in _INVISIBLE or cp in _BIDI:
            out.append(f"\\u{{{cp:04x}}}")
        else:
            out.append(ch)
    return "".join(out)


_INJECTION = [
    (r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?|rules)", "override attempt"),
    (r"disregard (all |any )?(the )?(previous|prior|above|system) ", "override attempt"),
    (r"(you are|act as) (now )?(in )?(developer|dan|god|jailbreak) mode", "jailbreak persona"),
    (r"<\s*(important|system|instructions?)\s*>", "fake privileged tag"),
    (r"\b(note|message|instructions?) (for|to) (the )?(ai|llm|assistant|agent|model|claude|copilot|cursor)s?\b",
     "text addressed to AI agents"),
    (r"do not (tell|inform|mention|show)( this)? (to )?the user", "asks to hide actions from the user"),
    (r"(read|cat|open|send|upload|exfiltrat\w*|post)\b.{0,60}(~/\.ssh|id_rsa|\.aws/credentials|\.env\b|"
     r"api[_ -]?key|private key|credentials)", "asks to read or send secrets"),
    (r"(curl|wget|iwr|invoke-webrequest)[^\n|]{0,200}\|\s*(ba|z)?sh\b", "pipe-to-shell"),
    (r"base64 (-d|--decode)[^\n]{0,80}\|\s*(ba|z)?sh", "obfuscated shell"),
]
_INJECTION_RE = [(re.compile(p, re.I | re.S), why) for p, why in _INJECTION]


def injection_markers(text: str) -> list[str]:
    """Heuristic signs of prompt injection / tool poisoning (high recall, read the context)."""
    found = []
    hidden = decode_tags(text)
    for rx, why in _INJECTION_RE:
        if rx.search(text) or (hidden and rx.search(hidden)):
            found.append(why)
    if hidden.strip():
        found.append(f"hidden tag-encoded text: {hidden[:80]!r}")
    return sorted(set(found))
