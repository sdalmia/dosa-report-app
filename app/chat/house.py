"""Business rules the model reads on every answer. Edit the markdown, not the code."""

from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "data" / "chat" / "house_notes.md"


def house_notes():
    try:
        text = _PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text[:2000]
