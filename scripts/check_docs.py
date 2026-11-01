#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that README links, anchors and images are valid and the SVGs are well-formed (run in CI)."""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slug(heading: str) -> str:
    h = re.sub(r"<[^>]+>", "", heading).strip().lower()
    return "".join(c for c in h if c.isalnum() or c in " -_").replace(" ", "-")


def main() -> int:
    bad = 0
    for md in ("README.md", "README.pl.md"):
        text = (ROOT / md).read_text(encoding="utf-8")
        anchors = {slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)}
        for m in re.finditer(r"\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"", text):
            target = m.group(1) or m.group(2)
            if target.startswith(("http", "mailto")):
                continue
            if target.startswith("#"):
                if target[1:] not in anchors:
                    print(f"{md}: broken anchor {target}")
                    bad += 1
            elif not (ROOT / target.split("#")[0]).exists():
                print(f"{md}: missing file {target}")
                bad += 1
    for svg in sorted((ROOT / "docs" / "images").glob("*.svg")):
        try:
            ET.parse(svg)
        except ET.ParseError as e:
            print(f"{svg.name}: invalid SVG: {e}")
            bad += 1
        if "<script" in svg.read_text(encoding="utf-8"):
            print(f"{svg.name}: contains a script")
            bad += 1
    print("docs OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
