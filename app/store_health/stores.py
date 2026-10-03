"""Store picker entries.

A store appears only when posist_daily.csv has a row. The label is that row's
store cell, unchanged. Region comes from the region column on that row.
"""

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
