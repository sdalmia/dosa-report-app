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

    A name the store master already lists uses that outlet's Posist label.
    Anything the master does not list still falls back to a unique longer label,
    so "Events & Catering" stays on "Dosa Coffee - Events & Catering".
    """
    from app.store_master import find_store

    found = []
    for row in rows:
        label = (row.get("posist_store") or "").strip()
        if label:
            found.append(label)
    deployments = [str(label).strip() for label in posist_labels if str(label).strip()]
    promoted = []
    pending = []
    for label in found:
        hit = find_store(label)
        if hit is not None:
            name = (hit.get("posist_name") or "").strip()
            if name and name not in deployments and name not in promoted:
                promoted.append(name)
            continue
        pending.append(label)
    outside = []
    for label in pending:
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
    kept = list(promoted)
    for label in sorted(set(outside), key=lambda text: (-len(text), text.casefold())):
        if unique_store_label(label, kept + deployments):
            continue
        if label in kept:
            continue
        kept.append(label)
    return kept


def _name_and_code(label):
    """Split a store label into name words and a store code.

    A leading 01 or 02 in front of the code is the region, not the store.
    Food Truck - 1 keeps the 1 in the name. 0002 and 002 are the same code.
    """
    words = label_words(label)
    code = None
    if len(words) >= 2 and words[-2] in {"01", "02"} and words[-1].isdigit() and len(words[-1]) >= 3:
        code = str(int(words[-1]))
        words = words[:-2]
    elif words and words[-1].isdigit() and len(words[-1]) >= 3:
        code = str(int(words[-1]))
        words = words[:-1]
    return words, code


def _is_subsequence(short, long):
    if not short:
        return False
    index = 0
    for token in long:
        if index < len(short) and token == short[index]:
            index += 1
    return index == len(short)


def match_menu_store(file_label, posist_labels):
    """Return the one Store Health label this menu-mix name clearly is.

    Ideal Plaza (01/0001) matches Ideal Plaza. Connaught Place matches
    Connaught place (02/0012). A name that fits two stores matches neither.
    """
    wanted_name, wanted_code = _name_and_code(file_label)
    if not wanted_name:
        return None
    hits = []
    for label in posist_labels:
        text = str(label).strip()
        if not text:
            continue
        name, code = _name_and_code(text)
        if wanted_code is not None and code is not None and wanted_code != code:
            continue
        shorter, longer = (wanted_name, name) if len(wanted_name) <= len(name) else (name, wanted_name)
        if not _is_subsequence(shorter, longer):
            continue
        hits.append(text)
    if wanted_code is not None:
        coded = [label for label in hits if _name_and_code(label)[1] == wanted_code]
        if len(coded) == 1:
            return coded[0]
        if len(coded) > 1:
            return None
    if len(hits) == 1:
        return hits[0]
    return None


def assign_rows(rows, label_key, posist_labels):
    """Map Posist labels to the one file row that names them.

    A label that hits no store, or more than one row, is left unassigned.
    """
    from app.store_master import resolve_store_label

    buckets = {}
    unmatched = []
    for row in rows:
        label = resolve_store_label(row.get(label_key), posist_labels)
        if label is None:
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
