"""Owner figures from the files already in the repo.

None means the input is missing. It is not scored, summed, or shown as zero.
A stored zero stays zero.
"""

import statistics
from datetime import timedelta

from app.store_health.contract import parse_number
from app.store_health.present import list_stores
from app.store_health.stores import assign_rows

from .figures import count_fig, date_label, fig, money_fig, month_label, pct_fig, plain_pct_fig, ratio_fig, score_fig

PRIOR_DAYS = 7
WORST_LIMIT = 5

WEIGHTS = (
    {
        "key": "sales_vs_mid",
        "label": "Sales vs forecast mid",
        "weight": 25,
        "formula": (
            "100 × summed gross ÷ summed forecast mid, on days in the month that have both. "
            "100 means gross matched mid. A day missing either figure is left out, not counted as zero."
        ),
    },
    {
        "key": "bills_wow",
        "label": "Bills, week on week",
        "weight": 15,
        "formula": (
            "100 plus the percent change in bills versus the same weekday one week earlier, "
            "on the latest day in the month. 100 means bills were flat. A missing earlier day stays blank."
        ),
    },
    {
        "key": "famepilot",
        "label": "Famepilot public rating",
        "weight": 20,
        "formula": (
            "100 × public rating ÷ 5, from the rating column in famepilot.csv. "
            "5.0 is 100. A blank rating is left out. The private rating is not used."
        ),
    },
    {
        "key": "audit",
        "label": "Mystery audit",
        "weight": 15,
        "formula": (
            "The avg_score percent in mystery_audit.csv, when it is a number. "
            "“Not in cycle” and other non-numbers are left out."
        ),
    },
    {
        "key": "productivity",
        "label": "Gross per active employee",
        "weight": 15,
        "formula": (
            "Month-to-date gross ÷ active_employees from keka_active.csv. "
            "The score indexes that figure to the median of stores with a count (the median scores 100). "
            "A blank or unmatched count is left out, not scored as zero."
        ),
    },
    {
        "key": "wastage",
        "label": "Wastage",
        "weight": 10,
        "formula": (
            "100 minus wastage_pct from data/store_health/wastage.csv, when that percent is present. "
            "An amount with no percent is shown and not scored. A missing file leaves the component blank."
        ),
    },
)


def percent_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (float(current) - float(previous)) / float(previous) * 100.0


def sales_score(gross, mid):
    if gross is None or mid is None or mid == 0:
        return None
    return float(gross) / float(mid) * 100.0


def bills_score(current, previous):
    change = percent_change(current, previous)
    if change is None:
        return None
    return 100.0 + change


def rating_score(rating):
    if rating is None:
        return None
    number = float(rating)
    if number < 0 or number > 5:
        return None
    return number / 5.0 * 100.0


def audit_score(text):
    return parse_number(text)


def wastage_score(pct):
    if pct is None:
        return None
    return 100.0 - float(pct)


def productivity_scores(per_person):
    """Index each store to the median of stores that have a figure.

    A missing figure stays None. The median itself is returned so the page can show it.
    A median of zero cannot be an index, so those scores stay blank too.
    """
    scores = {label: None for label in per_person}
    present = [value for value in per_person.values() if value is not None]
    if not present:
        return scores, None
    mid = float(statistics.median(present))
    if mid == 0:
        return scores, mid
    for label, value in per_person.items():
        if value is None:
            continue
        scores[label] = float(value) / mid * 100.0
    return scores, mid


def combine(parts):
    """Weighted mean of the parts that have a score. Missing parts drop out.

    Their weight is shared by the parts that remain. A missing score is not
    treated as zero, and a real zero stays in the mean.
    """
    included = [part for part in parts if part.get("score") is not None]
    total = sum(part["weight"] for part in included)
    scored = []
    for part in parts:
        item = dict(part)
        if part.get("score") is None or total == 0:
            item["included"] = False
            item["effective_weight"] = None
        else:
            item["included"] = True
            item["effective_weight"] = part["weight"] / total * 100.0
        scored.append(item)
    if not included or total == 0:
        composite = None
    else:
        composite = sum(part["score"] * part["weight"] for part in included) / total
    return composite, scored


def month_key(day):
    return f"{day.year:04d}-{day.month:02d}"


def months_in(feeds):
    found = {month_key(day) for (_store, day) in feeds["posist"]}
    return sorted(found, reverse=True)


def resolve_month(feeds, requested):
    available = months_in(feeds)
    if not available:
        return None, []
    if requested in available:
        return requested, available
    return available[0], available


def latest_day(feeds):
    days = [day for (_store, day) in feeds["posist"]]
    if not days:
        return None
    return max(days)


def _sum_present(values):
    present = [value for value in values if value is not None]
    if not present:
        return None
    return float(sum(present))


def _stores(feeds):
    return list_stores(feeds)


def _row(feeds, label, day):
    if day is None:
        return None
    return feeds["posist"].get((label, day))


def _region_name(region):
    return region or "Region not in the file"


def _group_rows(rows):
    order = []
    buckets = {}
    for name in ("East", "North"):
        order.append(name)
    for row in rows:
        name = _region_name(row["region"])
        if name not in buckets:
            buckets[name] = []
            if name not in order:
                order.append(name)
        buckets[name].append(row)
    groups = []
    for name in order:
        items = buckets.get(name) or []
        if items:
            groups.append({"name": name, "stores": items})
    return groups


def _store_change(feeds, store, day):
    current = _row(feeds, store.label, day)
    prior_day = day - timedelta(days=PRIOR_DAYS) if day else None
    prior = _row(feeds, store.label, prior_day)
    gross = current.get("gross") if current else None
    bills = current.get("bills") if current else None
    prior_gross = prior.get("gross") if prior else None
    prior_bills = prior.get("bills") if prior else None
    return {
        "id": store.id,
        "label": store.label,
        "region": store.region,
        "gross": money_fig(gross),
        "bills": count_fig(bills),
        "apb": money_fig(_apb(gross, bills)),
        "prior_gross": money_fig(prior_gross),
        "prior_bills": count_fig(prior_bills),
        "gross_change_pct": pct_fig(percent_change(gross, prior_gross)),
        "bills_change_pct": pct_fig(percent_change(bills, prior_bills)),
    }


def _apb(gross, bills):
    if gross is None or bills is None or bills == 0:
        return None
    return float(gross) / float(bills)


def _network_change(rows, current_key, prior_key):
    current_values = []
    prior_values = []
    for row in rows:
        current = row[current_key]["value"]
        prior = row[prior_key]["value"]
        if current is None or prior is None:
            continue
        current_values.append(current)
        prior_values.append(prior)
    if not current_values:
        return None, 0
    return percent_change(sum(current_values), sum(prior_values)), len(current_values)


def build_brief(feeds, attention, procurement):
    day = latest_day(feeds)
    prior_day = day - timedelta(days=PRIOR_DAYS) if day else None
    stores = _stores(feeds)
    rows = [_store_change(feeds, store, day) for store in stores] if day else []
    gross_values = []
    bill_values = []
    paired_gross = []
    paired_bills = []
    for row in rows:
        if row["gross"]["value"] is not None:
            gross_values.append(row["gross"]["value"])
        if row["bills"]["value"] is not None:
            bill_values.append(row["bills"]["value"])
        if row["gross"]["value"] is not None and row["bills"]["value"] is not None:
            paired_gross.append(row["gross"]["value"])
            paired_bills.append(row["bills"]["value"])
    gross_change, gross_compared = _network_change(rows, "gross", "prior_gross")
    bills_change, bills_compared = _network_change(rows, "bills", "prior_bills")
    paired_gross_sum = _sum_present(paired_gross)
    paired_bills_sum = _sum_present(paired_bills)
    network = {
        "gross": money_fig(_sum_present(gross_values)),
        "bills": count_fig(_sum_present(bill_values)),
        "apb": money_fig(_apb(paired_gross_sum, paired_bills_sum)),
        "apb_label": "APB, calculated as summed gross / summed bills",
        "stores_in_apb": len(paired_gross),
        "stores_on_day": len(rows),
        "gross_change_pct": pct_fig(gross_change),
        "bills_change_pct": pct_fig(bills_change),
        "gross_compared": gross_compared,
        "bills_compared": bills_compared,
    }
    worst_mid = []
    worst_week = []
    for row in rows:
        calendar = feeds["calendar"].get((row["label"], day)) if day else None
        mid = calendar.get("pred_mid") if calendar else None
        gross = row["gross"]["value"]
        variance = None
        if gross is not None and mid is not None and mid != 0:
            variance = (float(gross) - float(mid)) / float(mid) * 100.0
        if variance is not None:
            worst_mid.append(
                {
                    "id": row["id"],
                    "label": row["label"],
                    "gross": row["gross"],
                    "mid": money_fig(mid),
                    "variance_pct": pct_fig(variance),
                    "driver": (calendar.get("drivers") or "") if calendar else "",
                }
            )
        if row["gross_change_pct"]["value"] is not None:
            worst_week.append(
                {
                    "id": row["id"],
                    "label": row["label"],
                    "gross": row["gross"],
                    "prior_gross": row["prior_gross"],
                    "variance_pct": row["gross_change_pct"],
                }
            )
    worst_mid.sort(key=lambda item: (item["variance_pct"]["value"], item["label"].casefold()))
    worst_week.sort(key=lambda item: (item["variance_pct"]["value"], item["label"].casefold()))
    if day is None:
        empty = "posist_daily.csv has no dated rows, so there is no morning brief yet."
    else:
        empty = ""
    if not worst_mid:
        mid_empty = (
            "No store has both Posist gross and a forecast mid (pred_mid in sales_pred_vs_actual.csv) "
            "on this date, so there is no ranking versus forecast."
        )
    else:
        mid_empty = ""
    if not worst_week:
        week_empty = (
            "No store has gross on this date and on the same weekday one week earlier, "
            "so there is no ranking versus last week."
        )
    else:
        week_empty = ""
    return {
        "as_of": day.isoformat() if day else None,
        "as_of_label": date_label(day),
        "prior": prior_day.isoformat() if prior_day else None,
        "prior_label": date_label(prior_day),
        "sales_basis": "gross",
        "net": None,
        "net_note": "posist_daily.csv net is blank. Sales on this page are gross.",
        "empty": empty,
        "network": network,
        "regions": _group_rows(rows),
        "worst_vs_mid": worst_mid[:WORST_LIMIT],
        "worst_vs_mid_empty": mid_empty,
        "worst_vs_last_week": worst_week[:WORST_LIMIT],
        "worst_vs_last_week_empty": week_empty,
        "food_safety": attention["food_safety"],
        "food_safety_empty": attention["food_safety_empty"],
        "emergency": attention["emergency"],
        "emergency_empty": attention["emergency_empty"],
        "procurement": procurement["items"],
        "procurement_empty": procurement["empty"],
    }


def _rows_in_month(feeds, label, month):
    rows = []
    for (store, day), row in feeds["posist"].items():
        if store == label and month_key(day) == month:
            rows.append(row)
    rows.sort(key=lambda row: row["date"])
    return rows


def _sales_component(feeds, label, month):
    gross_values = []
    mid_values = []
    for (store, day), row in feeds["posist"].items():
        if store != label or month_key(day) != month:
            continue
        gross = row.get("gross")
        calendar = feeds["calendar"].get((label, day))
        mid = calendar.get("pred_mid") if calendar else None
        if gross is None or mid is None:
            continue
        gross_values.append(float(gross))
        mid_values.append(float(mid))
    gross_sum = _sum_present(gross_values)
    mid_sum = _sum_present(mid_values)
    score = sales_score(gross_sum, mid_sum)
    if not gross_values:
        raw = "No day in this month has both gross and a forecast mid."
    elif score is None:
        raw = f"{money_fig(gross_sum)['text']} gross vs {money_fig(mid_sum)['text']} mid. Mid sums to zero, so this is not scored."
    else:
        raw = (
            f"{money_fig(gross_sum)['text']} gross vs {money_fig(mid_sum)['text']} mid "
            f"on {len(gross_values)} days with both."
        )
    return score, raw


def _bills_component(feeds, label, month):
    rows = _rows_in_month(feeds, label, month)
    if not rows:
        return None, "No Posist row in this month."
    current = rows[-1]
    bills = current.get("bills")
    prior = _row(feeds, label, current["date"] - timedelta(days=PRIOR_DAYS))
    prior_bills = prior.get("bills") if prior else None
    score = bills_score(bills, prior_bills)
    if bills is None:
        raw = f"{date_label(current['date'])} has no bills figure."
    elif prior_bills is None:
        raw = f"{count_fig(bills)['text']} bills on {date_label(current['date'])}. The same weekday one week earlier is blank."
    else:
        raw = (
            f"{count_fig(bills)['text']} bills on {date_label(current['date'])} vs "
            f"{count_fig(prior_bills)['text']} on {date_label(current['date'] - timedelta(days=PRIOR_DAYS))}."
        )
    return score, raw


def _rating_component(row):
    if row is None:
        return None, "No Famepilot row for this store."
    rating = parse_number(row.get("rating"))
    written = (row.get("rating") or "").strip()
    score = rating_score(rating)
    if not written:
        raw = "Public rating is blank."
    elif score is None and rating is not None:
        raw = f"Public rating {written} is outside 0–5, so it is not scored."
    elif score is None:
        raw = f"Public rating {written} is not a number, so it is not scored."
    else:
        raw = f"Public rating {written} of 5."
    return score, raw


def _audit_component(row):
    if row is None:
        return None, "No mystery-audit row matches this store."
    written = (row.get("avg_score") or "").strip()
    score = audit_score(written)
    period = (row.get("period") or "").strip()
    prefix = f"{period}: " if period else ""
    if not written:
        raw = f"{prefix}avg_score is blank.".strip()
    elif score is None:
        raw = f"{prefix}{written}. Not a number, so it is not scored."
    else:
        raw = f"{prefix}{written}."
    return score, raw


def _wastage_for_month(wastage_rows, labels, month):
    specific = [row for row in wastage_rows if row.get("month") == month]
    general = [row for row in wastage_rows if not row.get("month")]
    assigned, _unmatched = assign_rows(specific, "store", labels)
    general_assigned, _unmatched_general = assign_rows(general, "store", labels)
    for label, row in general_assigned.items():
        assigned.setdefault(label, row)
    return assigned


def _wastage_component(row, file_present):
    if not file_present:
        return None, "No wastage file."
    if row is None:
        return None, "No wastage row for this store."
    pct = row.get("wastage_pct")
    amount = row.get("wastage_amount")
    score = wastage_score(pct)
    if pct is None and amount is None:
        return None, "Wastage cells are blank."
    if score is None:
        return None, f"Wastage amount {money_fig(amount)['text']} has no wastage_pct, so it is not scored."
    amount_bit = f", amount {money_fig(amount)['text']}" if amount is not None else ""
    return score, f"Wastage {pct:g}%{amount_bit}."


def _productivity_raw(gross, employees, matched_note):
    if employees is None:
        return None, matched_note or "active_employees is blank, so gross per person is not calculated."
    if employees == 0:
        return None, "active_employees is 0, so gross per person is not calculated."
    if gross is None:
        return None, "Month-to-date gross is blank, so gross per person is not calculated."
    per = float(gross) / float(employees)
    return per, f"{money_fig(gross)['text']} ÷ {count_fig(employees)['text']} active = {money_fig(per)['text']} per person."


def _assign_ranks(stores):
    ranked = [store for store in stores if store["score"]["value"] is not None]
    ranked.sort(key=lambda store: (-round(store["score"]["value"], 1), store["label"].casefold()))
    last_key = None
    last_rank = 0
    for index, store in enumerate(ranked, start=1):
        key = round(store["score"]["value"], 1)
        if last_key is None or key != last_key:
            last_rank = index
            last_key = key
        store["rank"] = last_rank
    ordered = ranked + [store for store in stores if store["score"]["value"] is None]
    return ordered


def build_scorecard(feeds, wastage, month):
    selected, available = resolve_month(feeds, month)
    stores = _stores(feeds)
    labels = [store.label for store in stores]
    wastage_rows = _wastage_for_month(wastage.get("rows") or [], labels, selected) if selected else {}
    per_person = {}
    prepared = []
    for store in stores:
        rows = _rows_in_month(feeds, store.label, selected) if selected else []
        gross = _sum_present([row.get("gross") for row in rows])
        keka = (feeds.get("keka_active_by_store") or {}).get(store.label)
        employees = parse_number(keka.get("active_employees")) if keka else None
        if keka is None:
            note = "No row in keka_active.csv matches this store."
        else:
            status = (keka.get("match_status") or "").strip()
            note = status or "active_employees is blank."
        per, per_raw = _productivity_raw(gross, employees, note)
        per_person[store.label] = per
        prepared.append(
            {
                "store": store,
                "rows": rows,
                "keka_note": note,
                "per_raw": per_raw,
                "employees": employees,
            }
        )
    indexes, median = productivity_scores(per_person)
    built = []
    for item in prepared:
        store = item["store"]
        sales, sales_raw = _sales_component(feeds, store.label, selected) if selected else (None, "No Posist month.")
        bills, bills_raw = _bills_component(feeds, store.label, selected) if selected else (None, "No Posist month.")
        rating, rating_raw = _rating_component((feeds.get("famepilot_by_store") or {}).get(store.label))
        audit, audit_raw = _audit_component((feeds.get("audit_by_store") or {}).get(store.label))
        waste, waste_raw = _wastage_component(wastage_rows.get(store.label), wastage.get("present"))
        prod_score = indexes.get(store.label)
        if item["per_raw"] and median is not None and prod_score is not None:
            prod_raw = f"{item['per_raw']} Indexed to the median {money_fig(median)['text']}."
        else:
            prod_raw = item["per_raw"]
        raws = {
            "sales_vs_mid": sales_raw,
            "bills_wow": bills_raw,
            "famepilot": rating_raw,
            "audit": audit_raw,
            "productivity": prod_raw,
            "wastage": waste_raw,
        }
        scores = {
            "sales_vs_mid": sales,
            "bills_wow": bills,
            "famepilot": rating,
            "audit": audit,
            "productivity": prod_score,
            "wastage": waste,
        }
        parts = []
        for spec in WEIGHTS:
            parts.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "weight": spec["weight"],
                    "score": scores[spec["key"]],
                    "raw": raws[spec["key"]],
                }
            )
        composite, scored = combine(parts)
        components = []
        for part in scored:
            components.append(
                {
                    "key": part["key"],
                    "label": part["label"],
                    "weight": part["weight"],
                    "score": score_fig(part["score"]),
                    "raw": part["raw"],
                    "included": part["included"],
                    "effective_weight": score_fig(part["effective_weight"]),
                }
            )
        built.append(
            {
                "id": store.id,
                "label": store.label,
                "region": store.region,
                "rank": None,
                "score": score_fig(composite),
                "components": components,
            }
        )
    ordered = _assign_ranks(built)
    return {
        "month": selected,
        "month_label": month_label(selected) if selected else "",
        "months": [{"key": key, "label": month_label(key)} for key in available],
        "weights": [
            {"key": spec["key"], "label": spec["label"], "weight": spec["weight"], "formula": spec["formula"]}
            for spec in WEIGHTS
        ],
        "wastage_empty": wastage.get("empty") or "",
        "median_productivity": money_fig(median),
        "stores": ordered,
        "ranked_count": sum(1 for store in ordered if store["rank"] is not None),
        "unranked_count": sum(1 for store in ordered if store["rank"] is None),
        "empty": "" if selected else "posist_daily.csv has no dated rows, so there is no month to score.",
    }


def _per(amount, employees):
    if amount is None or employees is None or employees == 0:
        return None
    return float(amount) / float(employees)


def build_labour(feeds):
    day = latest_day(feeds)
    month = month_key(day) if day else None
    stores = _stores(feeds)
    rows = []
    matched_gross = []
    matched_gross_employees = []
    matched_bills = []
    matched_bill_employees = []
    for store in stores:
        current = _row(feeds, store.label, day)
        gross = current.get("gross") if current else None
        bills = current.get("bills") if current else None
        month_rows = _rows_in_month(feeds, store.label, month) if month else []
        mtd_gross = _sum_present([row.get("gross") for row in month_rows])
        mtd_bills = _sum_present([row.get("bills") for row in month_rows])
        keka = (feeds.get("keka_active_by_store") or {}).get(store.label)
        employees = parse_number(keka.get("active_employees")) if keka else None
        status = (keka.get("match_status") or "").strip() if keka else ""
        if keka is None:
            status = "No row in keka_active.csv matches this store."
        elif employees is None and not status:
            status = "active_employees is blank."
        if employees is not None and employees != 0 and gross is not None:
            matched_gross.append(gross)
            matched_gross_employees.append(employees)
        if employees is not None and employees != 0 and bills is not None:
            matched_bills.append(bills)
            matched_bill_employees.append(employees)
        rows.append(
            {
                "id": store.id,
                "label": store.label,
                "region": store.region,
                "employees": count_fig(employees),
                "match_status": status,
                "day_gross": money_fig(gross),
                "day_bills": count_fig(bills),
                "day_gross_per": money_fig(_per(gross, employees)),
                "day_bills_per": ratio_fig(_per(bills, employees)),
                "mtd_gross": money_fig(mtd_gross),
                "mtd_bills": count_fig(mtd_bills),
                "mtd_gross_per": money_fig(_per(mtd_gross, employees)),
                "mtd_bills_per": ratio_fig(_per(mtd_bills, employees)),
            }
        )
    rows.sort(
        key=lambda row: (
            row["day_gross_per"]["value"] is None,
            -(row["day_gross_per"]["value"] or 0),
            row["label"].casefold(),
        )
    )
    return {
        "as_of": day.isoformat() if day else None,
        "as_of_label": date_label(day),
        "month": month,
        "month_label": month_label(month) if month else "",
        "note": "active_employees comes from keka_active.csv. A blank count is unmatched, not zero. Per-person figures stay blank when the count is blank.",
        "empty": "" if day else "posist_daily.csv has no dated rows, so labour productivity has no sales to divide.",
        "network": {
            "gross_per": money_fig(_per(_sum_present(matched_gross), _sum_present(matched_gross_employees))),
            "bills_per": ratio_fig(_per(_sum_present(matched_bills), _sum_present(matched_bill_employees))),
            "matched_stores": len(matched_gross_employees),
            "blank_stores": sum(1 for row in rows if row["employees"]["value"] is None),
        },
        "stores": rows,
    }


def _goals_for_month(goal_rows, labels, month):
    parsed = []
    warnings = []
    for row in goal_rows:
        store = (row.get("store") or "").strip()
        raw_month = (row.get("month") or "").strip()
        if not store:
            continue
        if raw_month != month:
            if raw_month and len(raw_month) != 7:
                warnings.append(f"{store}: month {raw_month} is not YYYY-MM, so that target was not applied.")
            continue
        target = parse_number(row.get("target_gross"))
        written = (row.get("target_gross") or "").strip()
        parsed.append({"store": store, "target": target, "written": written})
    assigned, unmatched = assign_rows(parsed, "store", labels)
    for row in unmatched:
        warnings.append(f"{row.get('store')} does not match one store, so that target was not applied.")
    return assigned, warnings


def build_goals(feeds, goals, month, festive_on):
    selected, available = resolve_month(feeds, month)
    stores = _stores(feeds)
    labels = [store.label for store in stores]
    assigned, warnings = _goals_for_month(goals.get("rows") or [], labels, selected) if selected else ({}, [])
    festive = _festive_dates(feeds)
    built = []
    for store in stores:
        rows = _rows_in_month(feeds, store.label, selected) if selected else []
        gross = _sum_present([row.get("gross") for row in rows])
        days = sum(1 for row in rows if row.get("gross") is not None)
        goal = assigned.get(store.label)
        target = goal.get("target") if goal else None
        written = (goal.get("written") or "").strip() if goal else ""
        note = ""
        progress = None
        bar = None
        empty = ""
        if goal is None:
            empty = "No target in data/goals.csv for this store and month."
        elif not written:
            empty = "target_gross is blank in data/goals.csv."
        elif target is None:
            empty = f"target_gross {written} is not a number, so the bar is not drawn."
        elif target == 0:
            note = "target_gross is 0, so the bar is not drawn."
        elif gross is None:
            empty = "No month-to-date gross in posist_daily.csv, so the bar is not drawn."
        else:
            progress = float(gross) / float(target) * 100.0
            bar = min(progress, 100.0)
        built.append(
            {
                "id": store.id,
                "label": store.label,
                "region": store.region,
                "mtd_gross": money_fig(gross),
                "days": days,
                "target": money_fig(target) if written and target is not None else fig(None),
                "target_written": written,
                "progress_pct": plain_pct_fig(progress),
                "bar_pct": bar,
                "empty": empty,
                "note": note,
            }
        )
    if festive:
        festive_empty = ""
    else:
        festive_empty = "No Puja or Diwali wording in the drivers column of sales_pred_vs_actual.csv."
    return {
        "month": selected,
        "month_label": month_label(selected) if selected else "",
        "months": [{"key": key, "label": month_label(key)} for key in available],
        "file_state": goals.get("state"),
        "file_message": goals.get("message") or "",
        "warnings": warnings,
        "festive_on": bool(festive_on) and bool(festive),
        "festive_requested": bool(festive_on),
        "festive_dates": festive,
        "festive_empty": festive_empty,
        "stores": built,
        "empty": "" if selected else "posist_daily.csv has no dated rows, so there is no month-to-date gross.",
    }


def _festive_dates(feeds):
    """Every Puja or Diwali date named in the forecast drivers.

    This is the whole file, not only the goals month, so 1 Nov stays visible
    with the rest of the Diwali-prep run.
    """
    found = {}
    for (_store, day), row in feeds.get("calendar", {}).items():
        driver = row.get("drivers") or ""
        low = driver.casefold()
        kinds = []
        if "puja" in low:
            kinds.append("Puja")
        if "diwali" in low:
            kinds.append("Diwali")
        if not kinds:
            continue
        current = found.get(day)
        if current is None:
            found[day] = {
                "iso": day.isoformat(),
                "label": date_label(day),
                "kinds": kinds,
                "driver": driver,
            }
        else:
            for kind in kinds:
                if kind not in current["kinds"]:
                    current["kinds"].append(kind)
    return [found[day] for day in sorted(found)]


def festive_available(feeds, month):
    if not month:
        return bool(_festive_dates(feeds))
    return any(day["iso"].startswith(month) for day in _festive_dates(feeds))
