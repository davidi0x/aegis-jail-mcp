"""Decoy credentials (honeytokens).

Where Aegis hides a real credential store, it can put a convincing fake in its
place (currently on Linux, where the hidden home is an empty tmpfs). The fakes
carry a per-run marker. An honest agent never needs them; if the marker later
appears in a network request, an MCP tool call, a changed file or the output,
the session is flagged with a TRIPWIRE: strong evidence of a compromised or
prompt-injected agent, rather than a guess.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from aegis_jail import paths

_TEMPLATES = {
    "~/.aws/credentials": "[default]\naws_access_key_id = AKIAAEGISDECOY{K}\naws_secret_access_key = {S}\n# {M}\n",
    "~/.ssh/id_rsa": "-----BEGIN OPENSSH PRIVATE KEY-----\n{M}\n{S}\n-----END OPENSSH PRIVATE KEY-----\n",
    "~/.ssh/id_ed25519": "-----BEGIN OPENSSH PRIVATE KEY-----\n{M}\n{S}\n-----END OPENSSH PRIVATE KEY-----\n",
    "~/.netrc": "machine github.com login aegis-decoy password {M}\n",
    "~/.git-credentials": "https://aegis-decoy:{M}@github.com\n",
    "~/.config/gh/hosts.yml": "github.com:\n    oauth_token: {M}\n    user: aegis-decoy\n",
    "~/.npmrc": "//registry.npmjs.org/:_authToken={M}\n",
    "~/.docker/config.json": '{{"auths": {{"https://index.docker.io/v1/": {{"auth": "{M}"}}}}}}\n',
}


def enabled() -> bool:
    return sys.platform.startswith("linux") and os.environ.get("AEGIS_DECOYS", "1") != "0"


def prepare(tmp: Path, hidden: list[Path], home_hidden: bool = True) -> dict[str, str]:
    """Write decoy files for hidden credential stores; returns {sandbox path: host file}.

    A decoy can only be placed where the sandbox has an empty stand-in: inside a hidden
    store that exists (it becomes an empty tmpfs), over a hidden credential *file*, or
    anywhere in the home directory when the whole home is hidden.
    """
    if not enabled():
        return {}
    marker = "AEGIS-DECOY-" + secrets.token_hex(8)
    key = secrets.token_hex(1).upper()
    out: dict[str, str] = {}
    d = tmp.parent / (tmp.name + "-decoys")
    hidden_set = {str(h) for h in hidden}
    for rel, tpl in _TEMPLATES.items():
        target = paths.expand(rel)
        # only where a hidden store sits at or above the decoy (so we never shadow a granted file)
        store = next((Path(h) for h in hidden_set if str(target) == h or str(target).startswith(h + os.sep)), None)
        if store is None:
            continue
        placeable = (home_hidden or (store.is_dir() and store != target) or target.is_file())
        if not placeable:
            continue
        d.mkdir(parents=True, exist_ok=True)
        f = d / rel.replace("~/", "").replace("/", "_")
        f.write_text(tpl.format(M=marker, K=key.ljust(2, "Z")[:2], S=secrets.token_hex(20)), encoding="utf-8")
        out[str(target)] = str(f)
    return out
