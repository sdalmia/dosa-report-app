"""Food-court stores whose in-store bills include mall bulk entries.

Manisquare and Forum Mall receive bulk transactions from the mall system.
Those bill counts and the APB built from them are not comparable with other
stores, so rankings, comparisons, and bill alerts leave them out.
"""

import re

MALL_BILL_NOTE = "Includes mall bulk entries"

_FORUM = re.compile(r"(^|[^a-z])forum([^a-z]|$)")


def is_mall_food_court(label):
    text = re.sub(r"\s+", " ", (label or "").casefold())
    if "manisquare" in text or "mani square" in text:
        return True
    if "forum mall" in text or _FORUM.search(text):
        return True
    return False
