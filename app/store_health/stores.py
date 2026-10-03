"""Store picker entries.

A store appears only when posist_daily.csv has a row. The label is that row's
store cell, unchanged. Region comes from the region column on that row.

Keka and mystery-audit files sometimes use a shorter label than the Posist UI
string. Those rows join a store only when one Posist label matches.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    id: str
    label: str
    region: str = ""

    def match_keys(self):
        text = self.label.strip()
        return {text} if text else set()


def store_from_label(name, region=""):
    """Build a picker entry. The visible label is the Posist string as written."""
    text = str(name).strip()
    slug = []
    for char in text.lower():
        slug.append(char if char.isalnum() else "-")
    store_id = "".join(slug).strip("-")
    while "--" in store_id:
        store_id = store_id.replace("--", "-")
    store_id = (store_id or "store")[:80]
    return Store(id=store_id, label=text, region=(region or "").strip())


_DOSA_PREFIX = re.compile(r"^dosa coffee\s*-\s*")


def label_words(label):
    """Words used to compare a file label with a Posist UI label."""
    text = str(label or "").strip().casefold()
    text = _DOSA_PREFIX.sub("", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.split()


def _consume(token, words, index):
    if index >= len(words):
        return None
    if words[index] == token:
        return index + 1
    # A short token such as "cp" or "ck" can stand for the initials of the
    # following words, and only when that reading is exact.
    if token.isalpha() and len(token) >= 2:
        letters = ""
        cursor = index
        while cursor < len(words) and words[cursor][:1].isalpha() and len(letters) < len(token):
            letters += words[cursor][0]
            cursor += 1
            if letters == token:
                return cursor
    return None


def _label_aligns(short, long):
    if not short:
        return False
    for start in range(len(long)):
        index = start
        matched = True
        for token in short:
            index = _consume(token, long, index)
            if index is None:
                matched = False
                break
        if matched:
            return True
    return False


def unique_store_label(file_label, posist_labels):
    """Return the one Posist label this file label names, or None.

    An exact label wins. A shorter label matches only when a single Posist
    label contains it. Ambiguous names such as "Salt Lake" match nothing.
    """
    wanted = label_words(file_label)
    if not wanted:
        return None
    labels = [str(label).strip() for label in posist_labels if str(label).strip()]
    exact = [label for label in labels if label_words(label) == wanted]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    loose = [label for label in labels if _label_aligns(wanted, label_words(label))]
    if len(loose) == 1:
        return loose[0]
    return None


def extra_store_labels(rows, posist_labels):
    """Labels from other feeds that are not on the Posist deployment report.

    A shorter label is dropped when it names a longer label already kept, so
    "Events & Catering" stays on "Dosa Coffee - Events & Catering".
    """
    found = []
    for row in rows:
        label = (row.get("posist_store") or "").strip()
        if label:
            found.append(label)
    outside = []
    deployments = [str(label).strip() for label in posist_labels if str(label).strip()]
    for label in found:
        wanted = label_words(label)
        if not wanted:
            continue
        # A name that lines up with one or more deployments is not a new store.
        # Ambiguous names such as "Salt Lake" stay unmatched.
        if any(
            label_words(deployment) == wanted or _label_aligns(wanted, label_words(deployment))
            for deployment in deployments
        ):
            continue
        outside.append(label)
    kept = []
    for label in sorted(set(outside), key=lambda text: (-len(text), text.casefold())):
        if unique_store_label(label, kept):
            continue
        kept.append(label)
    return kept


def assign_rows(rows, label_key, posist_labels):
    """Map Posist labels to the one file row that names them.

    A label that hits no store, or more than one row, is left unassigned.
    """
    buckets = {}
    unmatched = []
    for row in rows:
        label = unique_store_label(row.get(label_key), posist_labels)
        if label is None:
            unmatched.append(row)
            continue
        buckets.setdefault(label, []).append(row)
    assigned = {}
    for label, group in buckets.items():
        if len(group) == 1:
            assigned[label] = group[0]
        else:
            unmatched.extend(group)
    return assigned, unmatched
