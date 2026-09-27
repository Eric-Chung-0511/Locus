"""
In-app guide loader.

The guide text lives in Markdown, not in code: docs/help_en.md and
docs/help_zh.md have the same structure, and every section starts with an HTML
comment marker

    <!-- section: <key> -->

The text of a section runs from its marker to the next marker (or the end of
the file). Both files must contain exactly the keys in SECTION_KEYS; anything
else raises HelpError naming the file and the key, so a missing translation
never passes silently.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
SECTION_KEYS = ("start", "settings", "start_here", "summary", "confidence", "drivers", "risks", "recovery",
                "reviews", "late_start", "weather", "assumptions", "glossary")
LANG_FILES = {"en": "help_en.md", "zh": "help_zh.md"}
_MARKER = re.compile(r"<!--\s*section:\s*([a-z_]+)\s*-->")


class HelpError(ValueError):
    """Raised when a guide file is missing or does not match the section keys."""


def parse_sections(text: str, where: str) -> dict[str, str]:
    """Split guide Markdown into {key: section text}; text before the first marker is ignored."""
    parts = _MARKER.split(text)
    sections: dict[str, str] = {}
    for key, body in zip(parts[1::2], parts[2::2]):
        if key in sections:
            raise HelpError(f"{where}: section '{key}' appears more than once")
        sections[key] = body.strip()
    missing = [k for k in SECTION_KEYS if k not in sections]
    if missing:
        raise HelpError(f"{where}: missing section(s) {', '.join(missing)}")
    unknown = [k for k in sections if k not in SECTION_KEYS]
    if unknown:
        raise HelpError(f"{where}: unknown section(s) {', '.join(unknown)}; expected {SECTION_KEYS}")
    return sections


@lru_cache(maxsize=None)
def load_help(docs_dir: str = str(DOCS)) -> dict[str, dict[str, str]]:
    """Read and check both guide files once: {lang: {key: text}}."""
    guide: dict[str, dict[str, str]] = {}
    for lang, name in LANG_FILES.items():
        path = Path(docs_dir) / name
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HelpError(f"Guide file not found: {path}") from exc
        guide[lang] = parse_sections(text, str(path))
    return guide


def section(key: str, lang: str = "en") -> str:
    """Text of one guide section in the chosen language."""
    if key not in SECTION_KEYS:
        raise HelpError(f"Unknown guide section '{key}'; expected one of {SECTION_KEYS}")
    guide = load_help()
    if lang not in guide:
        raise HelpError(f"Unknown guide language '{lang}'; expected one of {tuple(guide)}")
    return guide[lang][key]
