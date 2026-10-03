"""Known restaurant brands and the positioning read for a scored site.

Logos for Starbucks, McDonald's, and KFC use Simple Icons paths (CC0).
The other marks are original name badges drawn for the map, not copies of
trademark artwork.

Retail rent is intentionally absent. CRE Matrix is the retail-rent source
for Indian high streets, and it is a paid product with no public API. This
module must not invent a rent figure from listings or from price level.
"""

import re

# Google's own price_level labels. These are coarse bands, not rupee amounts.
PRICE_LABELS = {
    0: "Free",
    1: "Inexpensive",
    2: "Moderate",
    3: "Expensive",
    4: "Very expensive",
}

# The anchor list in the site score is unchanged. These records only decide
# which places get a logo and which names count as similar brands.
BRANDS = [
    {
        "id": "starbucks",
        "name": "Starbucks",
        "logo": "brand_logos/starbucks.png",
        "aliases": ["starbucks"],
    },
    {
        "id": "mcdonalds",
        "name": "McDonald's",
        "logo": "brand_logos/mcdonalds.png",
        "aliases": ["mcdonalds", "mcdonald"],
    },
    {
        "id": "kfc",
        "name": "KFC",
        "logo": "brand_logos/kfc.png",
        "aliases": ["kfc", "kentucky fried chicken"],
    },
    {
        "id": "dominos",
        "name": "Domino's",
        "logo": "brand_logos/dominos.png",
        "aliases": ["dominos", "domino"],
    },
    {
        "id": "pizzahut",
        "name": "Pizza Hut",
        "logo": "brand_logos/pizzahut.png",
        "aliases": ["pizza hut"],
    },
    {
        "id": "chaipoint",
        "name": "Chai Point",
        "logo": "brand_logos/chaipoint.png",
        "aliases": ["chai point"],
    },
    {
        "id": "ccd",
        "name": "Cafe Coffee Day",
        "logo": "brand_logos/ccd.png",
        "aliases": ["cafe coffee day", "ccd"],
    },
    {
        "id": "haldirams",
        "name": "Haldiram's",
        "logo": "brand_logos/haldirams.png",
        "aliases": ["haldirams", "haldiram"],
    },
    {
        "id": "wowmomo",
        "name": "Wow Momo",
        "logo": "brand_logos/wowmomo.png",
        "aliases": ["wow momo", "wow momos"],
    },
    {
        "id": "biryaniblues",
        "name": "Biryani Blues",
        "logo": "brand_logos/biryaniblues.png",
        "aliases": ["biryani blues"],
    },
    {
        "id": "omsweets",
        "name": "Om Sweets",
        "logo": "brand_logos/omsweets.png",
        "aliases": ["om sweets", "om sweet"],
    },
]


def known_brand_choices():
    return [{"id": brand["id"], "name": brand["name"]} for brand in BRANDS]


def normalize_name(text):
    text = (text or "").lower().replace("’", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _alias_in_name(normalized_name, alias):
    name_tokens = normalized_name.split()
    alias_tokens = alias.split()
    if not name_tokens or not alias_tokens or len(alias_tokens) > len(name_tokens):
        return False

    def token_matches(token, alias_token):
        if token == alias_token:
            return True
        # "mcdonald" matches "mcdonalds"; short codes such as kfc and ccd stay exact.
        return len(alias_token) >= 4 and token.startswith(alias_token)

    width = len(alias_tokens)
    for start in range(len(name_tokens) - width + 1):
        window = name_tokens[start:start + width]
        if all(token_matches(token, alias_token) for token, alias_token in zip(window, alias_tokens)):
            return True
    return False


def match_brand(place_name):
    """Return the known brand for a place name, or None."""
    normalized = normalize_name(place_name)
    if not normalized:
        return None
    best = None
    best_len = -1
    for brand in BRANDS:
        for alias in brand["aliases"]:
            if _alias_in_name(normalized, alias) and len(alias) > best_len:
                best = brand
                best_len = len(alias)
    return best


def brand_for_query(query):
    """Map a search box entry onto a known brand when the words match one."""
    return match_brand(query)


def name_matches_brand_query(place_name, query):
    """True when a Places result is the brand the user asked to map.

    Keyword search matches any text Google indexed, so a name check is what
    keeps "Wow Momo" from pulling in "Wow China".
    """
    brand = brand_for_query(query)
    if brand:
        normalized = normalize_name(place_name)
        return any(_alias_in_name(normalized, alias) for alias in brand["aliases"])
    return _alias_in_name(normalize_name(place_name), normalize_name(query))


def price_band(price_level):
    """Return Google's band label, or None when this place has no price level."""
    if isinstance(price_level, bool) or not isinstance(price_level, int):
        return None
    return PRICE_LABELS.get(price_level)


def annotate_place(place):
    """Attach brand and bill fields. Does not change scoring inputs."""
    brand = match_brand(place.get("name") or "")
    if brand:
        place["brand_id"] = brand["id"]
        place["brand_name"] = brand["name"]
        place["logo"] = brand["logo"]
    else:
        place["brand_id"] = None
        place["brand_name"] = None
        place["logo"] = None
    place["bill_band"] = price_band(place.get("price_level"))
    return place


def site_verdict(score, breakdown):
    """Plain answer to 'should we open a restaurant here?'

    The number is the existing 0–10 score. A higher score is a stronger site.
    """
    if score >= 9:
        answer = "Yes. This is a strong site for a new restaurant."
        label = "Strong site"
    elif score >= 7:
        answer = "Yes. This looks like a strong site for a new restaurant."
        label = "Promising site"
    elif score >= 5:
        answer = "Maybe. There is some demand, but this is not a standout site for a new restaurant."
        label = "Possible site"
    else:
        answer = "No. This looks like a weak site for a new restaurant."
        label = "Weak site"

    explanation = (
        f"The restaurant-site score is {score} out of 10. "
        "A higher score means a stronger site for a new restaurant. "
        "It uses the same factors as before: "
        f"review energy {breakdown['energy_score']}/6 "
        f"(from {breakdown['total_reviews']} reviews nearby), "
        f"rating quality {breakdown['quality_score']}/1, "
        f"anchor brands {breakdown['anchor_score']}/1, "
        f"cuisine diversity {breakdown['diversity_score']}/1 "
        f"({breakdown['unique_cuisines']} cuisine types), "
        f"and transport {round(breakdown['transport_score'], 2)}/1."
    )
    return {"answer": answer, "label": label, "explanation": explanation}


def _bill_summary(places):
    counts = {level: 0 for level in PRICE_LABELS}
    missing = 0
    for place in places:
        band = price_band(place.get("price_level"))
        if band is None:
            missing += 1
        else:
            counts[place["price_level"]] += 1

    known = sum(counts.values())
    bands = [
        {"level": level, "label": PRICE_LABELS[level], "count": counts[level]}
        for level in range(5)
        if counts[level]
    ]
    present = [level for level, count in counts.items() if count]
    dominant = None
    if known == 0:
        headline = (
            "Unavailable. None of these restaurants returned a Google price level, "
            "so the bill is unavailable."
        )
    else:
        top = max(counts[level] for level in present)
        leaders = [level for level in present if counts[level] == top]
        if len(leaders) == 1:
            dominant = leaders[0]
            headline = (
                f"The most common bill band is {PRICE_LABELS[dominant]} "
                f"({counts[dominant]} of {known} places with a price level)."
            )
        else:
            tied = ", ".join(f"{PRICE_LABELS[level]} {counts[level]}" for level in sorted(leaders))
            headline = f"No single bill band dominates ({tied})."
        if missing == 1:
            headline += " 1 place has no price level, so its bill is unavailable."
        elif missing:
            headline += f" {missing} places have no price level, so their bill is unavailable."
    return {
        "bands": bands,
        "missing": missing,
        "known": known,
        "dominant_level": dominant,
        "headline": headline,
    }


def _cuisine_summary(places):
    counts = {}
    for place in places:
        cuisine = place.get("cuisine") or "Other"
        counts[cuisine] = counts.get(cuisine, 0) + 1
    rows = [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    specific = {name: count for name, count in counts.items() if name != "Other"}
    dominant = None
    if not places:
        headline = "No restaurants were returned for this radius."
    elif not specific:
        headline = "Google returned restaurants here, but their names did not match a known cuisine type."
    else:
        top = max(specific.values())
        leaders = sorted(name for name, count in specific.items() if count == top)
        if len(leaders) == 1:
            dominant = leaders[0]
            headline = (
                f"The restaurants already here are mostly {dominant} "
                f"({specific[dominant]} of {len(places)})."
            )
        else:
            listed = ", ".join(f"{name} ({specific[name]})" for name in leaders)
            headline = f"Several restaurant types share the area: {listed}."
    return {"rows": rows, "dominant": dominant, "headline": headline}


def _similar_brands(places, dominant_level):
    grouped = {}
    for place in places:
        brand_id = place.get("brand_id")
        if not brand_id:
            continue
        group = grouped.get(brand_id)
        if group is None:
            group = {
                "id": brand_id,
                "name": place.get("brand_name") or brand_id,
                "logo_url": place.get("logo_url"),
                "count": 0,
                "levels": {level: 0 for level in PRICE_LABELS},
                "missing_bill": 0,
            }
            grouped[brand_id] = group
        group["count"] += 1
        if place.get("logo_url"):
            group["logo_url"] = place["logo_url"]
        band = price_band(place.get("price_level"))
        if band is None:
            group["missing_bill"] += 1
        else:
            group["levels"][place["price_level"]] += 1

    rows = []
    for group in grouped.values():
        level_bits = [
            f"{PRICE_LABELS[level]} ({group['levels'][level]})"
            for level in range(5)
            if group["levels"][level]
        ]
        if level_bits:
            bill = ", ".join(level_bits)
            if group["missing_bill"]:
                bill += f"; bill unavailable for {group['missing_bill']}"
        else:
            bill = "Bill unavailable"
        rows.append({
            "id": group["id"],
            "name": group["name"],
            "logo_url": group["logo_url"],
            "count": group["count"],
            "bill": bill,
            "same_bill_band": bool(
                dominant_level is not None and group["levels"].get(dominant_level, 0) > 0
            ),
        })
    rows.sort(key=lambda row: (-row["count"], row["name"]))
    return rows


def _fit_sentence(cuisine, bill):
    band = PRICE_LABELS[bill["dominant_level"]] if bill["dominant_level"] is not None else None
    kind = cuisine["dominant"]
    if band and kind:
        return (
            f"A {band.lower()} {kind.lower()} brand fits this area. "
            "That is the bill band and restaurant type already drawing diners here."
        )
    if band and not kind:
        return (
            f"A {band.lower()} brand fits the bills diners already pay here. "
            "No single restaurant type dominates, so the cuisine position is open."
        )
    if kind and not band:
        return (
            f"The restaurants already here are mostly {kind.lower()}, but a price position "
            "is unavailable because there is no dominant Google price level."
        )
    if bill["known"] == 0:
        return (
            "A price position is unavailable because these restaurants have no Google price level. "
            "Use the restaurant types and the brands already here before choosing a concept."
        )
    return (
        "Bill bands and restaurant types are mixed, so no single brand position "
        "stands out from the places returned."
    )


def build_positioning(places):
    """Brand-fit read from the same Places rows that feed the heatmap.

    Rent is always unavailable. Bill text uses price_level only. Counts are
    tallies of those rows, never estimated rupees or rents.
    """
    bill = _bill_summary(places)
    cuisine = _cuisine_summary(places)
    brands = _similar_brands(places, bill["dominant_level"])
    return {
        "rent": {
            "status": "unavailable",
            "label": "Unavailable",
            "detail": (
                "A licensed retail-rent feed is not connected, so this result does not estimate rent."
            ),
        },
        "bill": bill,
        "cuisines": cuisine,
        "similar_brands": brands,
        "fit": _fit_sentence(cuisine, bill),
    }
