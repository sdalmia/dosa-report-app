"""Outlets the store picker can open.

Names come from the public list on dosacoffee.com. Region is East for Kolkata
and North for Delhi-NCR. Format is Kolkata or Delhi-NCR.

Deployment codes are left blank unless the Posist UI label is known. The only
known label is the contract example for Gurugram Sector-15. No sales figures
live here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    id: str
    public_name: str
    region: str
    format: str
    posist_deployment_name: str = ""
    deployment_code: str = ""
    extra_keys: tuple = ()

    @property
    def label(self):
        return self.posist_deployment_name or self.public_name

    def match_keys(self):
        keys = {self.public_name, self.label, *self.extra_keys}
        return {key.strip() for key in keys if key and str(key).strip()}


def _store(store_id, public_name, region, store_format, **kwargs):
    return Store(
        id=store_id,
        public_name=public_name,
        region=region,
        format=store_format,
        **kwargs,
    )


EAST = "East"
NORTH = "North"
KOLKATA = "Kolkata"
DELHI_NCR = "Delhi-NCR"

# Website order, Kolkata then Delhi-NCR. Nothing here is a preferred "first store".
CATALOGUE = (
    _store("kolkata-sector-3-salt-lake", "Sector 3, Salt Lake", EAST, KOLKATA),
    _store("kolkata-kalikapur", "Kalikapur", EAST, KOLKATA),
    _store("kolkata-sector-1-salt-lake", "Sector 1, Salt Lake", EAST, KOLKATA),
    _store("kolkata-ideal-plaza", "Ideal Plaza", EAST, KOLKATA),
    _store("kolkata-lake-town", "Lake Town", EAST, KOLKATA),
    _store("kolkata-rangoli-mall", "Rangoli Mall", EAST, KOLKATA),
    _store("kolkata-mani-square-mall", "Mani Square Mall", EAST, KOLKATA),
    _store(
        "kolkata-james-long-sarani",
        "James Long Sarani",
        EAST,
        KOLKATA,
        extra_keys=("Jameslong Sarani",),
    ),
    _store("kolkata-rosedale-plaza", "Rosedale Plaza", EAST, KOLKATA),
    _store("kolkata-calcutta-swimming-club", "Calcutta Swimming Club", EAST, KOLKATA),
    _store("kolkata-forum-mall", "Forum Mall", EAST, KOLKATA),
    _store(
        "kolkata-technopolis-sec-v",
        "Technopolis, Sec-V (Food Truck)",
        EAST,
        KOLKATA,
    ),
    _store("kolkata-santoshpur", "Santoshpur", EAST, KOLKATA),
    _store(
        "kolkata-new-town-action-area-ii",
        "New Town, Action Area-II (Cloud Kitchen)",
        EAST,
        KOLKATA,
    ),
    _store("kolkata-lake-road", "Lake Road", EAST, KOLKATA),
    _store("ncr-noida-sector-18", "Noida sector-18", NORTH, DELHI_NCR),
    _store("ncr-kalkaji", "Kalkaji", NORTH, DELHI_NCR),
    _store("ncr-pashchim-vihar", "Pashchim Vihar", NORTH, DELHI_NCR),
    _store("ncr-noida-sector-143", "Noida sector-143", NORTH, DELHI_NCR),
    _store("ncr-gurugram-sector-10", "Gurugram Sector-10", NORTH, DELHI_NCR),
    _store(
        "ncr-faridabad-sector-15",
        "Faridabad Sector-15",
        NORTH,
        DELHI_NCR,
        extra_keys=("Faridabad sec-15",),
    ),
    _store("ncr-rohini-sector-7", "Rohini Sector-7", NORTH, DELHI_NCR),
    _store(
        "ncr-gurugram-sector-15",
        "Gurugram Sector-15",
        NORTH,
        DELHI_NCR,
        posist_deployment_name="Dosa Coffee - Gurgaon Sec-15 (02/0010)",
        deployment_code="02/0010",
        extra_keys=("Gurgaon Sec-15 (02/0010)",),
    ),
    _store("ncr-gurugram-dlf-epitome", "Gurugram DLF Epitome", NORTH, DELHI_NCR),
    _store("ncr-pacific-jasola", "Pacific Outlet Mall, Jasola", NORTH, DELHI_NCR),
    _store("ncr-connaught-place", "Connaught Place, Delhi", NORTH, DELHI_NCR),
    _store("ncr-model-town", "Model Town", NORTH, DELHI_NCR),
    _store("ncr-chhattarpur", "Chhattarpur", NORTH, DELHI_NCR),
)


def _validate(stores):
    ids = {}
    keys = {}
    for store in stores:
        if store.region not in {EAST, NORTH, ""}:
            raise RuntimeError(f"{store.id} has region {store.region!r}")
        if store.format not in {KOLKATA, DELHI_NCR, ""}:
            raise RuntimeError(f"{store.id} has format {store.format!r}")
        if store.id in ids:
            raise RuntimeError(f"Duplicate store id {store.id}")
        ids[store.id] = store.id
        for key in store.match_keys():
            owner = keys.get(key)
            if owner and owner != store.id:
                raise RuntimeError(f"{key!r} is claimed by {owner} and {store.id}")
            keys[key] = store.id


_validate(CATALOGUE)


def store_from_feed(name):
    """A store that appears in a sales file and is not in the catalogue."""
    text = " ".join(name.split())
    slug = []
    for char in text.lower():
        slug.append(char if char.isalnum() else "-")
    store_id = "".join(slug).strip("-")
    while "--" in store_id:
        store_id = store_id.replace("--", "-")
    store_id = (store_id or "store")[:80]
    code = ""
    if "(" in text and text.endswith(")") and "/" in text:
        shown = text[text.rfind("(") + 1 : -1].strip()
        parts = shown.split("/")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            code = shown
    return Store(
        id=store_id,
        public_name=text,
        region="",
        format="",
        posist_deployment_name=text if text.startswith("Dosa Coffee - ") else "",
        deployment_code=code,
        extra_keys=(text,),
    )
