"""Owner landing figures from the store-health feeds already in the repo.

Nothing here invents a number. A missing cell stays blank and the page says
no data. Gross is Posist gross. APB is summed gross divided by summed bills.
"""

from datetime import timedelta
from pathlib import Path

from markupsafe import Markup

from app.procurement import procurement_tiles
from app.store_health.contract import data_directory, load_feeds, parse_number
from app.store_health.present import (
    POSIST_WINDOW_DAYS,
    _sum_present,
    _window_apb,
    _window_bounds,
    business_today,
    format_count,
    format_date,
    format_inr,
    format_pct,
    list_stores,
)

LAKH = 100_000
LOW_BILL_DROP = -15
LOW_RATING = 4


def _rows_on(feeds, day, region=None):
    found = []
    for (_store, row_day), row in feeds["posist"].items():
        if row_day != day:
            continue
        if region and (row.get("region") or "") != region:
            continue
        found.append(row)
    return found


def _change(new, old):
    if new is None or old is None or old == 0:
        return None
    return ((float(new) - float(old)) / float(old)) * 100


def _metric(rows, field, kind):
    return _sum_present(rows, field, kind)


def _region_block(feeds, region, start, end, compare_day):
    window_rows = []
    for (_store, day), row in feeds["posist"].items():
        if day < start or day > end:
            continue
        if region and (row.get("region") or "") != region:
            continue
        window_rows.append(row)
    gross = _metric(window_rows, "gross", "money")
    bills = _metric(window_rows, "bills", "count")
    apb = _window_apb(gross, bills)
    latest = _rows_on(feeds, end, region)
    prior = _rows_on(feeds, compare_day, region)
    latest_gross = _metric(latest, "gross", "money")
    prior_gross = _metric(prior, "gross", "money")
    latest_bills = _metric(latest, "bills", "count")
    prior_bills = _metric(prior, "bills", "count")
    latest_apb = _window_apb(latest_gross, latest_bills)
    prior_apb = _window_apb(prior_gross, prior_bills)
    return {
        "key": region or "all",
        "label": region or "All",
        "gross_value": gross,
        "bills_value": bills,
        "apb_value": apb,
        "gross": format_inr(gross) if gross is not None else "",
        "bills": format_count(bills) if bills is not None else "",
        "apb": format_inr(apb) if apb is not None else "",
        "gross_change": format_pct(_change(latest_gross, prior_gross)) if _change(latest_gross, prior_gross) is not None else "",
        "bills_change": format_pct(_change(latest_bills, prior_bills)) if _change(latest_bills, prior_bills) is not None else "",
        "apb_change": format_pct(_change(latest_apb, prior_apb)) if _change(latest_apb, prior_apb) is not None else "",
    }


def _store_rows(feeds, store, start, end):
    rows = []
    for (name, day), row in feeds["posist"].items():
        if name not in store.match_keys():
            continue
        if start <= day <= end:
            rows.append(row)
    return rows


def _store_on(feeds, store, day):
    for key in store.match_keys():
        row = feeds["posist"].get((key, day))
        if row is not None:
            return row
    return None


def _league(feeds, stores, start, end, region, low_only):
    ranked = []
    for store in stores:
        if region and store.region != region:
            continue
        rows = _store_rows(feeds, store, start, end)
        gross = _metric(rows, "gross", "money")
        bills = _metric(rows, "bills", "count")
        apb = _window_apb(gross, bills)
        latest = _store_on(feeds, store, end)
        prior = _store_on(feeds, store, end - timedelta(days=7))
        latest_bills = latest.get("bills") if latest else None
        prior_bills = prior.get("bills") if prior else None
        bills_change = _change(latest_bills, prior_bills)
        low = bills_change is not None and bills_change <= LOW_BILL_DROP
        if low_only and not low:
            continue
        if gross is None and bills is None:
            continue
        ranked.append({
            "id": store.id,
            "label": store.label,
            "region": store.region,
            "gross_value": gross,
            "gross": format_inr(gross) if gross is not None else "",
            "bills_change": format_pct(bills_change) if bills_change is not None else "",
            "apb": format_inr(apb) if apb is not None else "",
            "low": low,
        })
    ranked.sort(
        key=lambda item: (
            item["gross_value"] is None,
            -(item["gross_value"] or 0),
            item["label"].casefold(),
        )
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def _daily_gross(feeds, start, end):
    points = []
    day = start
    while day <= end:
        gross = _metric(_rows_on(feeds, day), "gross", "money")
        points.append({"date": day, "gross": gross})
        day += timedelta(days=1)
    return points


def _sum_band(feeds, day):
    lows, mids, highs = [], [], []
    for (_store, row_day), row in feeds["calendar"].items():
        if row_day != day:
            continue
        if row.get("pred_low") is not None:
            lows.append(row["pred_low"])
        if row.get("pred_mid") is not None:
            mids.append(row["pred_mid"])
        if row.get("pred_high") is not None:
            highs.append(row["pred_high"])
    def total(values):
        if not values:
            return None
        cents = sum(int(round(float(value) * 100)) for value in values)
        return cents / 100.0
    return total(lows), total(mids), total(highs)


def _network_file(directory):
    repo = Path(__file__).resolve().parents[1]
    candidates = [
        repo / "data" / "posist" / "sales_pred_vs_actual.csv",
        Path(directory) / "network_sales_pred_vs_actual.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _read_network(path):
    import csv
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            rows.append(raw)
    return rows


def _network_by_day(path):
    """Network band in rupees. A *_L column, or a whole file of small lakhs, is converted."""
    table = _read_network(path)
    if not table:
        return {}, "no rows"
    sample = table[0]
    lakh_columns = any(name.endswith("_L") for name in sample)
    by_day = {}
    mids = []
    for raw in table:
        from app.store_health.contract import parse_date
        day = parse_date(raw.get("date"))
        if day is None:
            continue
        def take(name):
            if name + "_L" in raw and (raw.get(name + "_L") or "").strip():
                number = parse_number(raw.get(name + "_L"))
                return None if number is None else number * LAKH
            number = parse_number(raw.get(name))
            return number
        low, mid, high = take("pred_low"), take("pred_mid"), take("pred_high")
        if mid is not None:
            mids.append(mid)
        by_day[day] = (low, mid, high)
    note = path.name
    if not lakh_columns and mids and max(mids) < 500:
        scaled = {}
        for day, (low, mid, high) in by_day.items():
            scaled[day] = tuple(None if value is None else value * LAKH for value in (low, mid, high))
        by_day = scaled
        note = f"{path.name} (values under 500 read as lakhs)"
    elif lakh_columns:
        note = f"{path.name} (lakh columns)"
    return by_day, note


def _chart(feeds, directory, start, end):
    actual = {point["date"]: point["gross"] for point in _daily_gross(feeds, start, end)}
    network_path = _network_file(directory)
    band_note = "Sum of store shares in sales_pred_vs_actual.csv. A blank share is not treated as zero."
    band = {}
    if network_path is not None:
        try:
            band, band_note = _network_by_day(network_path)
            band_note = f"Network file {band_note}"
        except OSError:
            band = {}
            band_note = f"{network_path.name} could not be read"
    else:
        last_calendar = max((row_day for (_store, row_day) in feeds["calendar"]), default=None)
        stop = max(end, last_calendar) if last_calendar else end
        cursor = start
        while cursor <= stop:
            band[cursor] = _sum_band(feeds, cursor)
            cursor += timedelta(days=1)
        # _sum_band returns a tuple even when all None. Drop empty days from the domain
        # only after we know the last day that has a number.
    dates = set(actual)
    last_band = None
    for day, values in band.items():
        if any(value is not None for value in values):
            dates.add(day)
            if last_band is None or day > last_band:
                last_band = day
    if not dates:
        return {"points": [], "source": band_note, "last_band": "", "svg": ""}
    first, final = min(dates), max(dates)
    points = []
    cursor = first
    while cursor <= final:
        low, mid, high = band.get(cursor, (None, None, None))
        points.append({
            "iso": cursor.isoformat(),
            "label": format_date(cursor),
            "gross": actual.get(cursor),
            "low": low,
            "mid": mid,
            "high": high,
        })
        cursor += timedelta(days=1)
    return {
        "points": points,
        "source": band_note,
        "last_band": format_date(last_band) if last_band else "",
        "svg": Markup(_svg(points)),
    }


def _svg(points):
    nums = []
    for point in points:
        for key in ("gross", "low", "high"):
            if point[key] is not None:
                nums.append(point[key])
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    if hi == lo:
        hi = lo + 1
    width, height = 360, 160
    pad_l, pad_r, pad_t, pad_b = 4, 4, 8, 18
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    count = len(points)

    def x_at(index):
        if count == 1:
            return pad_l + inner_w / 2
        return pad_l + inner_w * index / (count - 1)

    def y_at(value):
        return pad_t + inner_h * (1 - (value - lo) / (hi - lo))

    def poly(key):
        parts = []
        for index, point in enumerate(points):
            value = point[key]
            if value is None:
                if parts:
                    parts.append(None)
                continue
            parts.append(f"{x_at(index):.1f},{y_at(value):.1f}")
        segments = []
        current = []
        for part in parts:
            if part is None:
                if len(current) > 1:
                    segments.append(" ".join(current))
                current = []
            else:
                current.append(part)
        if len(current) > 1:
            segments.append(" ".join(current))
        return segments

    band_shapes = []
    current_low = []
    current_high = []
    def flush():
        if len(current_low) < 2 or len(current_high) < 2:
            return
        forward = " ".join(current_low)
        back = " ".join(reversed(current_high))
        band_shapes.append(f"{forward} {back}")
    for index, point in enumerate(points):
        if point["low"] is None or point["high"] is None:
            flush()
            current_low = []
            current_high = []
            continue
        current_low.append(f"{x_at(index):.1f},{y_at(point['low']):.1f}")
        current_high.append(f"{x_at(index):.1f},{y_at(point['high']):.1f}")
    flush()
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Daily gross and forecast band">',
    ]
    for shape in band_shapes:
        parts.append(f'<polygon points="{shape}" class="chart-band"></polygon>')
    for key, css in (("mid", "chart-mid"), ("gross", "chart-gross")):
        for segment in poly(key):
            parts.append(f'<polyline points="{segment}" class="{css}"></polyline>')
    if points:
        parts.append(
            f'<text x="{pad_l}" y="{height - 4}" class="chart-label">{points[0]["label"]}</text>'
        )
        parts.append(
            f'<text x="{width - pad_r}" y="{height - 4}" text-anchor="end" class="chart-label">{points[-1]["label"]}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _next_days(feeds, today):
    days = []
    for offset in range(8):
        day = today + timedelta(days=offset)
        tiers = set()
        drivers = set()
        seen = False
        for (_store, row_day), row in feeds["calendar"].items():
            if row_day != day:
                continue
            seen = True
            if row.get("tier"):
                tiers.add(row["tier"])
            if row.get("drivers"):
                drivers.add(row["drivers"])
        item = {
            "iso": day.isoformat(),
            "label": format_date(day),
            "weekday": day.strftime("%a"),
            "tier": "",
            "driver": "",
        }
        if not seen:
            days.append(item)
            continue
        if len(tiers) == 1:
            item["tier"] = next(iter(tiers))
        elif len(tiers) > 1:
            item["tier"] = "Varies by store"
        if len(drivers) == 1:
            item["driver"] = next(iter(drivers))
        elif len(drivers) > 1:
            item["driver"] = "Varies by store"
        days.append(item)
    return days


def _one_row(value):
    if isinstance(value, list):
        return value[-1] if value else None
    return value


def _rating(row):
    if not row:
        return None, None
    return parse_number(row.get("rating")), parse_number(row.get("review_count"))


def _reputation(feeds, stores):
    by_label = {store.label: store for store in stores}
    weighted_sum = 0.0
    weight = 0.0
    review_total = 0.0
    have_reviews = False
    rated = []
    for label, rows in (feeds.get("famepilot_by_store") or {}).items():
        if not rows:
            continue
        row = _one_row(rows)
        rating, reviews = _rating(row)
        if reviews is not None:
            review_total += reviews
            have_reviews = True
        if rating is None or reviews is None or reviews <= 0:
            continue
        weighted_sum += rating * reviews
        weight += reviews
        store = by_label.get(label)
        rated.append({
            "label": label,
            "id": store.id if store else "",
            "rating": f"{rating:.2f}",
            "reviews": format_count(reviews),
            "rating_value": rating,
        })
    rated.sort(key=lambda item: (item["rating_value"], item["label"].casefold()))
    return {
        "source": "famepilot.csv",
        "period": "Past 30 days preset on the Famepilot capture. The dates printed were 26 Sep 26 to 02 Oct 26, which is 7 days.",
        "rating": f"{weighted_sum / weight:.2f}" if weight else "",
        "rating_note": "Review-weighted. A store with no rating is left out, not scored as zero.",
        "reviews": format_count(review_total) if have_reviews else "",
        "worst": rated[:3],
    }


def _reelo(feeds):
    visits = []
    redeemed = []
    ranges = []
    skipped = 0
    for row in feeds.get("reelo") or []:
        status = (row.get("match_status") or "").strip().casefold()
        if status == "not in reelo":
            skipped += 1
            continue
        visit = parse_number(row.get("visits_last30d"))
        times = parse_number(row.get("times_rewards_redeemed"))
        if visit is not None:
            visits.append(visit)
        if times is not None:
            redeemed.append(times)
        span = (row.get("date_range") or "").strip()
        if span and span not in ranges:
            ranges.append(span)
    return {
        "source": "reelo.csv",
        "period": ranges[0] if len(ranges) == 1 else "",
        "periods": ranges,
        "visits": format_count(sum(visits)) if visits else "",
        "redeemed": format_count(sum(redeemed)) if redeemed else "",
        "not_in_reelo": skipped,
    }


def _alerts(feeds, stores, end):
    alerts = []
    compare = end - timedelta(days=7) if end else None
    for store in stores:
        if end is None:
            break
        latest = _store_on(feeds, store, end)
        prior = _store_on(feeds, store, compare)
        latest_bills = latest.get("bills") if latest else None
        prior_bills = prior.get("bills") if prior else None
        change = _change(latest_bills, prior_bills)
        if change is not None and change <= LOW_BILL_DROP:
            alerts.append({
                "kind": "Bills",
                "text": f"{store.label}: bills {format_pct(change)} versus the same weekday last week.",
                "href": store.id,
            })
    for label, rows in (feeds.get("famepilot_by_store") or {}).items():
        if not rows:
            continue
        rating, reviews = _rating(_one_row(rows))
        if rating is None or rating >= LOW_RATING:
            continue
        review_bit = f" from {format_count(reviews)} reviews" if reviews is not None else ""
        alerts.append({
            "kind": "Rating",
            "text": f"{label}: public rating {rating:.2f}{review_bit}.",
            "href": "",
        })
    return alerts


def build_owner_dashboard(feeds=None, today=None, region="", low_only=False, procurement_dir=None):
    feeds = feeds if feeds is not None else load_feeds()
    today = today or business_today()
    start, end = _window_bounds(feeds)
    regions = []
    compare_label = ""
    window_label = ""
    if start is not None and end is not None:
        window_label = f"{format_date(start)} through {format_date(end)}"
        compare_day = end - timedelta(days=7)
        compare_label = f"{format_date(end)} vs {format_date(compare_day)}"
        for name in (None, "East", "North"):
            regions.append(_region_block(feeds, name, start, end, compare_day))
    stores = list_stores(feeds)
    league = _league(feeds, stores, start, end, region, low_only) if start else []
    chart = _chart(feeds, feeds.get("directory") or data_directory(), start, end) if start else {
        "points": [], "source": "", "last_band": "", "svg": "",
    }
    days_in_window = 0
    if start and end:
        days_in_window = sum(1 for offset in range((end - start).days + 1) if _rows_on(feeds, start + timedelta(days=offset)))
    return {
        "window_label": window_label,
        "compare_label": compare_label,
        "days_with_rows": days_in_window,
        "window_days": POSIST_WINDOW_DAYS,
        "regions": regions,
        "league": league,
        "region_filter": region,
        "low_only": low_only,
        "low_rule": "Low performers: bills on the newest Posist day are 15% or more below the same weekday last week. A store missing either day is not called low.",
        "chart": chart,
        "next_days": _next_days(feeds, today),
        "reputation": _reputation(feeds, stores),
        "reelo": _reelo(feeds),
        "alerts": _alerts(feeds, stores, end),
        "procurement": procurement_tiles(procurement_dir),
        "today": today,
    }
