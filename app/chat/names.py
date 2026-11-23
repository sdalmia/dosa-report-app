"""How a figure or a store name is written.

Money uses Rs and Indian grouping. A bill count is a whole number.
Store names drop the brand prefix and the Posist code.
"""

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ALIASES = None


def _aliases():
    global _ALIASES
    if _ALIASES is not None:
        return _ALIASES
    path = _ROOT / "data" / "chat" / "owners.json"
    found = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("names") if isinstance(payload, dict) else {}
        if isinstance(raw, dict):
            found = {str(key).casefold(): str(value) for key, value in raw.items()}
    except (OSError, json.JSONDecodeError):
        found = {}
    _ALIASES = found
    return found


def indian_digits(value, decimals=0):
    """8,33,288 or 1,309. The last group is three digits, then pairs."""
    number = float(value)
    sign = "-" if number < 0 else ""
    if decimals:
        text = f"{abs(number):.{decimals}f}"
        whole, frac = text.split(".")
    else:
        whole = str(int(round(abs(number))))
        frac = ""
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(parts)) + "," + tail
    if frac:
        return f"{sign}{grouped}.{frac}"
    return f"{sign}{grouped}"


def rs_rupees(value):
    """Nearest rupee, Indian grouped. Rs 8,33,288 rather than 833288.05."""
    return "Rs " + indian_digits(value, 0)


def rs_lakh(value):
    """A figure already counted in lakhs. Rs 8.33 L."""
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}Rs {abs(number):.2f} L"


def bill_count(value):
    return indian_digits(value, 0)


def clean_store_name(name):
    """Drop the brand and the code, then use the display spelling."""
    text = str(name or "")
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"(?i)^dosa coffee\s*-\s*", "", text)
    text = re.sub(r"\s+\d{1,2}/\d{3,4}\s*$", "", text)
    text = re.sub(r"\s+\d{3,5}\s*$", "", text)
    text = " ".join(text.split())
    if not text:
        return "That store"
    words = []
    for word in text.split(" "):
        if word in {",", "-"}:
            words.append(word)
            continue
        bits = []
        for part in word.split("-"):
            if not part:
                bits.append(part)
            elif part.isupper() and 2 <= len(part) <= 4:
                bits.append(part)
            elif part.isalpha():
                bits.append(part[:1].upper() + part[1:].lower())
            else:
                bits.append(part[:1].upper() + part[1:] if part else part)
        words.append("-".join(bits))
    cleaned = " ".join(words)
    return _aliases().get(cleaned.casefold(), cleaned)


def clip_label(text, limit=32):
    """Shorten only on a space, never in the middle of a word."""
    label = " ".join(str(text or "").split())
    if len(label) <= limit:
        return label
    cut = label.rfind(" ", 0, limit)
    if cut <= 0:
        return label
    return label[:cut]
