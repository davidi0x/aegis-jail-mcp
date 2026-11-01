"""Credential detection (data-loss prevention) used across Aegis.

* the working copy hides project files that hold credentials (.env, keys, ...),
* the network proxy blocks plaintext requests that carry secrets or decoys,
* the MCP jail blocks tool calls that would hand secrets to a server,
* the Claude Code hook blocks commands / fetches that embed secrets,
* run reports flag secrets an agent wrote into files or printed.

Only high-confidence formats are matched, to keep false positives rare.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath

PATTERNS: list[tuple[str, str]] = [
    ("AWS access key", r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    ("GitLab token", r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    ("Anthropic API key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI API key", r"\bsk-(proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("Stripe live key", r"\b(sk|rk)_live_[A-Za-z0-9]{20,}"),
    ("Hugging Face token", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("npm token", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("private key", r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----"),
    ("Aegis decoy credential", r"AEGIS-DECOY-[0-9a-f]{8,}|AKIAAEGISDECOY[0-9A-Z]{2,}"),
    ("Aegis canary", r"AEGIS-CANARY-SECRET"),
]
_COMPILED = [(name, re.compile(rx)) for name, rx in PATTERNS]


def find_secrets(text: str) -> list[str]:
    """Names of credential types present in text (deduplicated)."""
    return sorted({name for name, rx in _COMPILED if rx.search(text)})


def is_decoy_hit(text: str) -> bool:
    return any(n in ("Aegis decoy credential", "Aegis canary") for n in find_secrets(text))


# Files inside a project that usually hold credentials. They are left out of the
# agent's working copy (and never deleted by `apply`) unless a profile exposes them.
SECRET_FILE_GLOBS = [
    ".env", ".env.*", "*.env", ".envrc", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "service-account*.json", "*.tfstate", "*.tfstate.backup",
    "kubeconfig", "*.kubeconfig", "secrets.yml", "secrets.yaml", ".secrets", "*.ovpn",
]
SAFE_TEMPLATES = (".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults")


def is_secret_filename(relpath: str) -> bool:
    name = PurePosixPath(relpath).name
    if name.lower() in SAFE_TEMPLATES:
        return False
    return any(fnmatch.fnmatch(name, g) for g in SECRET_FILE_GLOBS)


def file_has_secret(data: bytes) -> list[str]:
    if b"\0" in data[:4096]:
        return []
    return [s for s in find_secrets(data[:262144].decode("utf-8", "replace"))
            if not s.startswith("Aegis")]
