"""One row per outlet. Other pages look a name up here instead of guessing.

A blank cell stays blank. A label that is not listed, or that would fit two
outlets, does not match.
"""

import csv
import os
import re
from pathlib import Path

COLUMNS = (
    "store_id",
    "display_name",
    "city",
    "region",
    "format",
    "posist_name",
    "posist_code",
    "gbp_name",
    "gbp_maps_url",
    "gbp_rating",
    "gbp_reviews",
    "gbp_verified",
    "reelo_name",
    "reelo_status",
    "famepilot_name",
    "keka_location",
    "swiggy_id",
    "zomato_id",
    "status",
    "notes",
)

# Mystery-audit labels that are not the outlet's own name. They are exact
# keys written into the master, not a guess made while a page is rendering.
AUDIT_NAMES = {
    "CP": "Connaught place (02/0012)",
    "Jasola": "Pacific mall, Jasola (02/0011)",
    "Shalimar": "Shalimar Bagh (02/0015)",
    "Quest": "Dosa Coffee - Quest Mall (01/0016)",
    "New Town CK": "Dosa Coffee - New Town - Cloud Kitchen (01/0013)",
}

GAP_OWNER = "Sanjoy / Subhra"
NOT_ON_REELO = "not on Reelo by choice"
UNKNOWN_STATUS = "unknown, asked Sanjoy"

# Posist Insights outlets that are not in the latest sales drop.
# FRA and Events stay unknown until Sanjoy answers.
# GK1 Cloud Kitchen and Chattarpur are closed: out of rankings and not gaps.
INSIGHTS_OUTLETS = (
    {
        "posist_name": "DEMO OUTLET",
        "display_name": "DEMO OUTLET",
        "status": "test",
        "notes": "Posist Insights test outlet.",
    },
    {
        "posist_name": "Salt Lake Sec-3 (Not In Use)",
        "display_name": "Salt Lake Sec-3, not in use",
        "status": "closed",
        "notes": "Posist Insights lists this outlet as not in use.",
    },
    {
        "posist_name": "Dosa Coffee, FRA (02/0017)",
        "display_name": "FRA",
        "region": "North",
        "posist_code": "02/0017",
        "status": UNKNOWN_STATUS,
        "notes": "Status asked of Sanjoy.",
    },
)
ASKED_SANJOY = {
    "Dosa Coffee - Events & Catering",
    "Dosa Coffee, FRA (02/0017)",
}
CLOSED_OUTLETS = {
    "GK1 Cloud Kitchen (02/0002)",
    "Chattarpur (02/0005)",
}
CLOSING_OUTLETS = {
    "Sec 15 Faridabad (02/0007)": "closing 31 Oct",
}

_BRAND = re.compile(r"^dosa coffee\s*-\s*", re.IGNORECASE)
_CODE = re.compile(r"(?i)(0[12])\s*/\s*(\d{3,4})")
_BARE_CODE = re.compile(r"\((\d{3,4})\)\s*$")
_CACHE = {}


def master_path():
    override = os.environ.get("STORE_MASTER_FILE", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "store_master.csv"


def clear_cache():
    _CACHE.clear()


def _read_dicts(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalise_key(value):
    text = str(value or "").casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def name_words(label):
    text = _BRAND.sub("", str(label or "").strip())
    text = _CODE.sub(" ", text)
    text = _BARE_CODE.sub(" ", text)
    return tuple(normalise_key(text).split())


def posist_code(label, region=""):
    """Region/store, four digits, such as 01/0011. Unknown stays blank."""
    text = str(label or "").strip()
    found = _CODE.search(text)
    if found:
        return f"{found.group(1)}/{int(found.group(2)):04d}"
    bare = _BARE_CODE.search(text)
    if not bare:
        return ""
    prefix = {"east": "01", "north": "02"}.get(str(region or "").strip().casefold(), "")
    if not prefix:
        return ""
    return f"{prefix}/{int(bare.group(1)):04d}"


def _code_number(label):
    text = str(label or "")
    found = _CODE.search(text)
    if found:
        return int(found.group(2))
    bare = _BARE_CODE.search(text)
    if bare:
        return int(bare.group(1))
    return None


def display_name_for(label):
    text = _BRAND.sub("", str(label or "").strip())
    text = _CODE.sub("", text)
    text = _BARE_CODE.sub("", text)
    return " ".join(text.replace("(", " ").replace(")", " ").split())


def _slug(label):
    from app.store_health.stores import store_from_label

    return store_from_label(label).id


def _city(address):
    text = str(address or "")
    folded = text.casefold()
    for needle, city in (
        ("gurugram", "Gurugram"),
        ("gurgaon", "Gurgaon"),
        ("faridabad", "Faridabad"),
        ("noida", "Noida"),
        ("howrah", "Howrah"),
        ("kolkata", "Kolkata"),
        ("new delhi", "New Delhi"),
        ("delhi", "Delhi"),
        ("bidhannagar", "Kolkata"),
    ):
        if needle in folded:
            return city
    return ""


def _format(name, address):
    blob = f"{name} {address}".casefold()
    if "cloud kitchen" in blob:
        return "cloud kitchen"
    if "truck" in blob:
        return "truck"
    if "catering" in blob or re.search(r"\bevents?\b", blob):
        return "events"
    if "kiosk" in blob:
        return "kiosk"
    if "food court" in blob:
        return "food court"
    if str(address or "").strip():
        return "dine-in"
    return ""


def _blank_row():
    return {column: "" for column in COLUMNS}


def _is_word_subsequence(short, long):
    if not short or len(short) > len(long):
        return False
    index = 0
    for token in long:
        if index < len(short) and token == short[index]:
            index += 1
    return index == len(short)


def _attach(label, rows):
    """The one outlet this exact label names, or None when it is ambiguous."""
    text = str(label or "").strip()
    if not text:
        return None
    folded = text.casefold()
    if folded in {"brand", "not in reelo", "no keka location"}:
        return None
    code = posist_code(text, "")
    if code:
        hits = [row for row in rows if row["posist_code"] == code]
        if len(hits) == 1:
            return hits[0]
        return None
    words = name_words(text)
    if not words:
        return None
    number = _code_number(text)

    def accept(row):
        if number is not None and _code_number(row["posist_name"]) not in {None, number}:
            return False
        return True

    exact = [row for row in rows if name_words(row["posist_name"]) == words and accept(row)]
    if len(exact) == 1:
        prefix_of_another = any(
            name_words(other["posist_name"])[: len(words)] == words
            and name_words(other["posist_name"]) != words
            for other in rows
        )
        if prefix_of_another and number is None:
            return None
        return exact[0]
    if len(exact) > 1:
        return None
    # A label such as "Pacific Jasola" names one outlet once the extra word
    # "mall" is skipped. Two outlets still match nothing.
    loose = []
    for row in rows:
        outlet = name_words(row["posist_name"])
        if not _is_word_subsequence(words, outlet) or not accept(row):
            continue
        loose.append(row)
    if len(loose) == 1:
        return loose[0]
    return None


def _place_sentence(note):
    text = str(note or "").casefold()
    if "scored the mall" in text:
        return "The site score is for the mall, not the store."
    if "scored the club" in text:
        return "The site score is for the club, not the store."
    if "same site" in text:
        return "The site score is shared with another store."
    if "suggestion" in text:
        return "The suggested address does not match the store name."
    return ""


def _gbp_sentence(note):
    text = str(note or "").casefold()
    if "please confirm" in text or "inferred" in text:
        return "The Google listing should be confirmed before it is treated as this store."
    if "ungrouped" in text or "outside the dosa coffee group" in text:
        return "The Google listing sits outside the Dosa Coffee group."
    return ""


def build_rows(posist_path, gbp_path, places_path, store_health_dir):
    """Rows for store_master.csv. Unknown cells stay blank."""
    posist = _read_dicts(posist_path)
    seen = {}
    order = []
    for raw in posist:
        name = (raw.get("store") or "").strip()
        if not name or name in seen:
            continue
        row = _blank_row()
        row["posist_name"] = name
        row["region"] = (raw.get("region") or "").strip()
        row["posist_code"] = posist_code(name, row["region"])
        row["display_name"] = display_name_for(name)
        row["store_id"] = _slug(name)
        row["status"] = "trading"
        seen[name] = row
        order.append(name)

    for label, target in AUDIT_NAMES.items():
        if target not in seen:
            raise ValueError(f"{label} has no outlet {target}")

    gbp_groups = {}
    for raw in _read_dicts(gbp_path):
        name = (raw.get("posist_store") or "").strip()
        if not name or name not in seen:
            continue
        gbp_groups.setdefault(name, []).append(raw)

    places = {}
    for raw in _read_dicts(places_path):
        name = (raw.get("posist_store") or "").strip()
        if name and name not in places:
            places[name] = raw

    health = Path(store_health_dir) if store_health_dir else None
    reelo = _read_dicts(health / "reelo.csv") if health else []
    fame = _read_dicts(health / "famepilot.csv") if health else []
    keka = _read_dicts(health / "keka.csv") if health else []
    keka_active = _read_dicts(health / "keka_active.csv") if health else []
    audit = _read_dicts(health / "mystery_audit.csv") if health else []
    menu = _read_dicts(health / "menu_mix.csv") if health else []

    extra_names = []
    for raw in reelo + fame + keka + keka_active:
        label = (raw.get("posist_store") or "").strip()
        if label and label not in seen and label not in extra_names:
            extra_names.append(label)
    # A longer label is the outlet. "Events & Catering" stays on
    # "Dosa Coffee - Events & Catering" instead of becoming its own row.
    extra_names.sort(key=lambda text: (-len(text), text.casefold()))
    for label in extra_names:
        if _attach(label, list(seen.values())):
            continue
        if label.casefold() in {"not in reelo", "no keka location"}:
            continue
        row = _blank_row()
        row["posist_name"] = label
        row["posist_code"] = posist_code(label, "")
        if row["posist_code"].startswith("01/"):
            row["region"] = "East"
        elif row["posist_code"].startswith("02/"):
            row["region"] = "North"
        row["display_name"] = display_name_for(label)
        row["store_id"] = _slug(label)
        row["notes"] = "No sales in the latest Posist drop."
        if label in ASKED_SANJOY:
            row["status"] = UNKNOWN_STATUS
        seen[label] = row
        order.append(label)

    for spec in INSIGHTS_OUTLETS:
        name = spec["posist_name"]
        if name in seen:
            continue
        row = _blank_row()
        row["posist_name"] = name
        row["display_name"] = spec.get("display_name") or display_name_for(name)
        row["region"] = spec.get("region") or ""
        row["posist_code"] = spec.get("posist_code") or posist_code(name, row["region"])
        row["store_id"] = _slug(name)
        row["status"] = spec.get("status") or ""
        row["notes"] = spec.get("notes") or ""
        seen[name] = row
        order.append(name)

    rows = [seen[name] for name in order]
    known = {row["posist_name"]: [row["posist_name"]] for row in rows}

    def remember(label, row):
        text = str(label or "").strip()
        if not text or text.casefold() in {"not in reelo", "no keka location"}:
            return
        bucket = known[row["posist_name"]]
        if text not in bucket:
            bucket.append(text)

    for name, group in gbp_groups.items():
        row = seen[name]
        named = [item for item in group if (item.get("gbp_name") or "").strip()]
        if not named:
            continue
        verified = [item for item in named if (item.get("verified") or "").strip().casefold() == "verified"]
        chosen = verified[0] if verified else named[0]
        row["gbp_name"] = (chosen.get("gbp_name") or "").strip()
        row["gbp_maps_url"] = (chosen.get("maps_url") or "").strip()
        row["gbp_rating"] = (chosen.get("rating") or "").strip()
        row["gbp_reviews"] = (chosen.get("reviews") or "").strip()
        row["gbp_verified"] = (chosen.get("verified") or "").strip()
        if not row["city"]:
            row["city"] = _city(chosen.get("address"))
        if not row["format"]:
            row["format"] = _format(row["posist_name"], chosen.get("address"))
        sentences = []
        if any((item.get("verified") or "").strip().casefold() == "duplicate" for item in named) or len(named) > 1:
            sentences.append("A second Google listing points at this store.")
        for item in named:
            sentence = _gbp_sentence(item.get("match_note"))
            if sentence and sentence not in sentences:
                sentences.append(sentence)
        if sentences:
            row["notes"] = " ".join(part for part in (row["notes"], " ".join(sentences)) if part).strip()

    for name, raw in places.items():
        row = seen.get(name)
        if row is None:
            continue
        if not row["city"]:
            row["city"] = _city(raw.get("site_scored"))
        sentence = _place_sentence(raw.get("note"))
        if sentence and sentence not in row["notes"]:
            row["notes"] = " ".join(part for part in (row["notes"], sentence) if part).strip()

    for raw in reelo:
        row = _attach(raw.get("posist_store"), rows)
        if row is None:
            continue
        remember(raw.get("posist_store"), row)
        status = (raw.get("match_status") or "").strip().casefold()
        reelo_name = (raw.get("reelo_store") or "").strip()
        if status in {"matched", "inferred"} and reelo_name and reelo_name.casefold() != "not in reelo":
            row["reelo_name"] = reelo_name
            remember(reelo_name, row)
        if status == "inferred":
            sentence = "The Reelo name is not a confirmed match."
            if sentence not in row["notes"]:
                row["notes"] = " ".join(part for part in (row["notes"], sentence) if part).strip()

    for raw in fame:
        row = _attach(raw.get("posist_store"), rows)
        if row is None:
            continue
        remember(raw.get("posist_store"), row)
        location = (raw.get("famepilot_location") or "").strip()
        if location:
            row["famepilot_name"] = location
            remember(location, row)

    for raw in keka_active:
        row = _attach(raw.get("posist_store"), rows)
        if row is None:
            continue
        remember(raw.get("posist_store"), row)
        status = (raw.get("match_status") or "").strip().casefold()
        location = (raw.get("keka_location") or "").strip()
        if status == "matched" and location and location.casefold() != "no keka location":
            row["keka_location"] = location
            remember(location, row)

    for raw in keka:
        row = _attach(raw.get("posist_store"), rows)
        if row is None:
            continue
        remember(raw.get("posist_store"), row)
        status = (raw.get("match_status") or "").strip().casefold()
        location = (raw.get("keka_location") or "").strip()
        if status == "matched" and location and location.casefold() != "no keka location" and not row["keka_location"]:
            row["keka_location"] = location
            remember(location, row)
        if status == "inferred":
            sentence = "The staff location is not a confirmed match."
            if sentence not in row["notes"]:
                row["notes"] = " ".join(part for part in (row["notes"], sentence) if part).strip()

    for raw in audit:
        if (raw.get("status") or "").strip().casefold() == "brand aggregate":
            continue
        label = (raw.get("store") or "").strip()
        target = AUDIT_NAMES.get(label)
        row = seen.get(target) if target else _attach(label, rows)
        if row is None:
            continue
        remember(label, row)

    for raw in menu:
        row = _attach(raw.get("store"), rows)
        if row is not None:
            remember(raw.get("store"), row)

    for row in rows:
        if not row["format"]:
            row["format"] = _format(row["posist_name"], "")
        names = []
        for name in known[row["posist_name"]]:
            if name and name not in names and name != row["posist_name"]:
                names.append(name)
        if names:
            prefix = "Known names: " + " | ".join(names)
            row["notes"] = "\n".join(part for part in (prefix, row["notes"]) if part)
        if row["posist_name"] in ASKED_SANJOY:
            row["status"] = UNKNOWN_STATUS
        if row["posist_name"] in CLOSED_OUTLETS:
            row["status"] = "closed"
        if row["posist_name"] in CLOSING_OUTLETS:
            row["status"] = CLOSING_OUTLETS[row["posist_name"]]
        if row.get("reelo_name"):
            row["reelo_status"] = ""
        else:
            row["reelo_status"] = NOT_ON_REELO

    return rows


def write_master(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


def load_rows(path=None):
    path = Path(path) if path else master_path()
    rows = []
    for raw in _read_dicts(path):
        rows.append({column: (raw.get(column) or "").strip() for column in COLUMNS})
    return rows


def known_names(notes):
    names = []
    for line in str(notes or "").splitlines():
        if line.startswith("Known names:"):
            names.extend(part.strip() for part in line.split(":", 1)[1].split("|") if part.strip())
    return names


def human_notes(notes):
    lines = []
    for line in str(notes or "").splitlines():
        if line.startswith("Known names:"):
            continue
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def _words_prefix_another(words, rows, own):
    if not words:
        return False
    for other in rows:
        if other is own:
            continue
        other_words = name_words(other.get("posist_name"))
        if len(other_words) > len(words) and other_words[: len(words)] == words:
            return True
    return False


def _index_key(bucket, key, row):
    token = normalise_key(key)
    if not token:
        return
    current = bucket.get(token)
    if current is None:
        bucket[token] = row
    elif current is not row:
        bucket[token] = None


class StoreIndex:
    def __init__(self, rows):
        self.rows = rows
        self.by_key = {}
        for row in rows:
            for column in (
                "store_id",
                "posist_name",
                "posist_code",
                "reelo_name",
                "famepilot_name",
                "keka_location",
            ):
                _index_key(self.by_key, row.get(column), row)
            # "Salt Lake" is the short name of one outlet and the start of another.
            # It is not a key. The full label still is.
            display = row.get("display_name")
            if not _words_prefix_another(name_words(display), rows, row):
                _index_key(self.by_key, display, row)
            for name in known_names(row.get("notes")):
                _index_key(self.by_key, name, row)
        gbp_counts = {}
        for row in rows:
            token = normalise_key(row.get("gbp_name"))
            if token:
                gbp_counts[token] = gbp_counts.get(token, 0) + 1
        for row in rows:
            token = normalise_key(row.get("gbp_name"))
            if token and gbp_counts.get(token) == 1:
                _index_key(self.by_key, row.get("gbp_name"), row)

    def find(self, label):
        token = normalise_key(label)
        if not token:
            return None
        hit = self.by_key.get(token)
        if hit is not None:
            return hit
        code = posist_code(label, "")
        if code:
            coded = [row for row in self.rows if row.get("posist_code") == code]
            if len(coded) == 1:
                return coded[0]
        return None


def get_index(path=None):
    path = Path(path) if path else master_path()
    key = str(path)
    stamp = path.stat().st_mtime if path.is_file() else None
    cached = _CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    index = StoreIndex(load_rows(path) if path.is_file() else [])
    _CACHE[key] = (stamp, index)
    return index


def find_store(label, path=None):
    return get_index(path).find(label)


def store_status(row):
    return (row.get("status") or "").strip()


def is_closed_status(status):
    return str(status or "").strip().casefold() == "closed"


def is_closing_status(status):
    return str(status or "").strip().casefold().startswith("closing")


def is_trading(label, path=None):
    """Rankings include a store the master calls trading, or one that is closing.

    A closed store stays out. A name the master does not list stays eligible,
    so a fixture store still ranks.
    """
    row = find_store(label, path)
    if row is None:
        return True
    status = store_status(row)
    return status.casefold() == "trading" or is_closing_status(status)


def allows_growth(label, path=None):
    """Closed and closing stores get no growth actions."""
    row = find_store(label, path)
    if row is None:
        return True
    status = store_status(row)
    if is_closed_status(status) or is_closing_status(status):
        return False
    return True


def resolve_store_label(label, posist_labels, path=None):
    """The Posist label this name is, when the master names exactly one of them."""
    row = find_store(label, path)
    if row is None:
        return None
    name = (row.get("posist_name") or "").strip()
    if not name:
        return None
    allowed = [str(item).strip() for item in posist_labels if str(item).strip()]
    if allowed and name not in allowed:
        return None
    if not allowed:
        return None
    return name


def store_gaps(row):
    """Every listed system this outlet is missing, with an owner and a status.

    A closed store is not a gap.
    """
    if is_closed_status(store_status(row)):
        return []
    gaps = []

    def add(kind, label, status, detail):
        gaps.append(
            {
                "kind": kind,
                "label": label,
                "owner": GAP_OWNER,
                "status": status,
                "detail": detail,
            }
        )

    if not row.get("gbp_name"):
        add("google", "No Google listing", "Needs a listing", "There is no Google listing for this store.")
    verified = (row.get("gbp_verified") or "").strip().casefold()
    if row.get("gbp_name") and verified != "verified":
        add("unverified", "Unverified listing", "Needs verification", "The Google listing is not verified.")
    note = human_notes(row.get("notes"))
    if "second Google listing" in note:
        add("duplicate", "Duplicate listing", "Needs a cleanup", "A second Google listing points at this store.")
    if "not a confirmed match" in note or "should be confirmed" in note or "does not match" in note or "not the store" in note or "shared with another" in note or "outside the Dosa Coffee group" in note:
        add("name", "Name mismatch", "Needs a check", note)
    # A store left off Reelo on purpose is not a gap.
    if not row.get("swiggy_id") or not row.get("zomato_id"):
        missing = []
        if not row.get("swiggy_id"):
            missing.append("Swiggy")
        if not row.get("zomato_id"):
            missing.append("Zomato")
        add(
            "delivery",
            "No Swiggy or Zomato id",
            "Needs the ids",
            "Missing " + " and ".join(missing) + ".",
        )
    return gaps
