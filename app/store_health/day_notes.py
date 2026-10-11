"""Store-days that stay on the page and stay out of comparisons.

A protest-affected day and a status-unknown day are Posist rows. They stay
visible, with a badge, and they are left out of week-over-week comparisons,
forecast accuracy, and low-sales alerts.
"""

from datetime import date

PROTEST = "Protest-affected"
UNKNOWN = "Status unknown"
NOTE_DAY = date(2026, 10, 10)

NOTES = {
    ("Connaught place (02/0012)", NOTE_DAY): PROTEST,
    ("Gurgaon DLF (02/0009)", NOTE_DAY): PROTEST,
    ("Dosa Coffee - Food Truck - 1 (0008)", NOTE_DAY): UNKNOWN,
}

QUALITY_NOTE = (
    "10 Oct: East ops matches Posist. Delhi NCR ops net is within 0.4% of Posist. "
    "Delhi NCR ops was 65 bills short (22 at Gurgaon Sec-15). "
    "The report was likely pulled before close."
)


def badge_for(store, day):
    if day is None:
        return ""
    for label in _labels(store):
        badge = NOTES.get((label, day))
        if badge:
            return badge
    return ""


def excluded_from_comparisons(store, day):
    return bool(badge_for(store, day))


def notes_between(store, start, end):
    if start is None or end is None:
        return []
    labels = set(_labels(store))
    found = []
    for (label, day), badge in NOTES.items():
        if label in labels and start <= day <= end:
            found.append((day, badge))
    found.sort()
    return found


def quality_note_for(feeds):
    posist = (feeds or {}).get("posist") or {}
    if any(day == NOTE_DAY for (_store, day) in posist):
        return QUALITY_NOTE
    return ""


def badges_on(day):
    found = []
    for (label, note_day), badge in NOTES.items():
        if note_day == day:
            found.append({"label": label, "badge": badge, "iso": note_day.isoformat()})
    found.sort(key=lambda item: item["label"].casefold())
    return found


def _labels(store):
    if store is None:
        return []
    if isinstance(store, str):
        return [store]
    label = getattr(store, "label", "")
    return [label] if label else []
