"""Store-days that stay on the page and stay out of comparisons.

A protest-affected day and a status-unknown day are Posist rows. They stay
visible, with a badge, and they are left out of week-over-week comparisons,
forecast accuracy, and low-sales alerts.
"""

from datetime import date, timedelta

PROTEST = "Protest-affected"
UNKNOWN = "Status unknown"
CLOSED = "Closed"
NOTE_DAY = date(2026, 10, 10)
FOOD_TRUCK = "Dosa Coffee - Food Truck - 1 (0008)"
FARIDABAD = "Sec 15 Faridabad (02/0007)"
# Last Posist row is 22 Oct. From the next morning the outlet is closed.
FARIDABAD_CLOSED_FROM = date(2026, 10, 23)

NOTES = {
    ("Connaught place (02/0012)", NOTE_DAY): PROTEST,
    ("Gurgaon DLF (02/0009)", NOTE_DAY): PROTEST,
    (FOOD_TRUCK, NOTE_DAY): UNKNOWN,
    (FOOD_TRUCK, date(2026, 10, 11)): CLOSED,
    (FOOD_TRUCK, date(2026, 10, 16)): CLOSED,
    (FOOD_TRUCK, date(2026, 10, 17)): CLOSED,
    (FOOD_TRUCK, date(2026, 10, 18)): CLOSED,
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


def store_closed_on(store, day):
    """The outlet did not trade this day, even when the file has no sales row.

    Faridabad Sec-15 stopped on the night of 22 Oct 2026. Later days are closed
    the way Chattarpur and GK1 Cloud Kitchen are closed: shown as Closed, and
    left out of gaps, averages, and low-sales flags.
    """
    if day is None:
        return False
    if badge_for(store, day) == CLOSED:
        return True
    for label in _labels(store):
        if label == FARIDABAD and day >= FARIDABAD_CLOSED_FROM:
            return True
    return False


def excluded_from_comparisons(store, day):
    return bool(badge_for(store, day)) or store_closed_on(store, day)


def is_closed_sales_row(row):
    """A closed trading day stays on the file and stays out of averages.

    A note that merely mentions an earlier closure, such as "closed till 9",
    is not a closed day. Tony's closed rows start with "Closed:" or use status closed.
    """
    if not row:
        return False
    status = str(row.get("status") or "").strip().casefold()
    if status == "closed":
        return True
    notes = str(row.get("notes") or "").strip().casefold()
    return notes.startswith("closed:")


def notes_between(store, start, end):
    if start is None or end is None:
        return []
    labels = set(_labels(store))
    found = {}
    for (label, day), badge in NOTES.items():
        if label in labels and start <= day <= end:
            found[day] = badge
    if FARIDABAD in labels:
        cursor = start if start > FARIDABAD_CLOSED_FROM else FARIDABAD_CLOSED_FROM
        while cursor <= end:
            found.setdefault(cursor, CLOSED)
            cursor += timedelta(days=1)
    return sorted(found.items())


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
