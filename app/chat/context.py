"""The data packet sent with a question. Compact, but it includes store rows."""

from app.chat.house import house_notes


def _inr(value):
    if value is None:
        return ""
    number = float(value)
    sign = "-" if number < 0 else ""
    whole = str(int(round(abs(number))))
    if len(whole) <= 3:
        return sign + "₹" + whole
    tail = whole[-3:]
    head = whole[:-3]
    parts = []
    while len(head) > 2:
        parts.append(head[-2:])
        head = head[:-2]
    if head:
        parts.append(head)
    return sign + "₹" + ",".join(reversed(parts)) + "," + tail


def _num(value, digits=1):
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _lines(rows, columns):
    if not rows:
        return "(none)"
    head = " | ".join(columns)
    body = []
    for row in rows:
        body.append(" | ".join(str(row.get(column) if row.get(column) is not None else "") for column in columns))
    return head + "\n" + "\n".join(body)


def _sales_table(rows):
    shaped = []
    for row in rows:
        shaped.append({
            "store": row.get("store") or "",
            "region": row.get("region") or "",
            "gross": _inr(row.get("gross")),
            "bills": "" if row.get("bills") is None else str(int(round(row["bills"]))),
            "apb": "left out (mall bulk)" if row.get("mall_bulk") else _inr(row.get("apb")),
        })
    return _lines(shaped, ["store", "region", "gross", "bills", "apb"])


def build_context(question, data):
    """Text the model reads. Finance and HR stay off unless this role may see them."""
    role = data.get("role") or "ops"
    windows = data.get("sales_windows") or {}
    summary = data.get("summary") or {}
    latest = windows.get("latest") or summary.get("as_of_date") or ""
    parts = [
        "House notes:",
        house_notes() or "(none)",
        "",
        "Dates covered:",
        f"Latest sales day in the file: {latest or 'not loaded'}.",
        f"Last 7 sales days: {windows.get('week_start') or '?'} to {latest or '?'}.",
        f"Month-to-date: {windows.get('month_start') or '?'} to {latest or '?'}.",
        f"Sales summary as_of_date: {summary.get('as_of_date') or 'not loaded'}.",
        f"Reelo period: {data.get('reelo_period') or 'not loaded'}.",
        "If the question asks about a date after the latest sales day, say the file does not cover that date and use the latest day instead.",
        "Manisquare and Forum are mall bulk stores. Their APB and bills are left out of comparisons. Their gross is still listed.",
        "",
        "Network sales summary:",
        _summary_line(summary),
        "",
        f"Each store on the latest sales day ({latest or 'unknown'}). Gross and APB are rupees.",
        _sales_table(windows.get("latest_rows") or []),
        "",
        "Each store, sum of the last 7 sales days:",
        _sales_table(windows.get("week_rows") or []),
        "",
        "Each store, month-to-date:",
        _sales_table(windows.get("mtd_rows") or []),
        "",
        "Week-on-week gross change (latest day versus 7 days earlier):",
        _lines(
            [
                {
                    "store": row.get("store"),
                    "date": row.get("date"),
                    "gross": _inr(row.get("gross")),
                    "prior_gross": _inr(row.get("prior_gross")),
                    "pct": _num(row.get("pct")),
                    "note": row.get("note") or "",
                }
                for row in (data.get("movers") or [])
            ],
            ["store", "date", "gross", "prior_gross", "pct", "note"],
        ),
        "",
        "Versus the mid forecast, on the latest day that has both figures:",
        _lines(
            [
                {
                    "store": row.get("store"),
                    "date": row.get("date"),
                    "actual": _inr(row.get("actual")),
                    "mid": _inr(row.get("mid")),
                    "pct": _num(row.get("pct")),
                }
                for row in (data.get("forecast") or [])
            ],
            ["store", "date", "actual", "mid", "pct"],
        ),
        "",
        "October mystery audit, lowest score first. Score is a percent.",
        _lines(
            [
                {"store": row.get("store"), "period": row.get("period"), "score": _num(row.get("score"))}
                for row in (data.get("october_audit") or [])
            ],
            ["store", "period", "score"],
        ),
        "",
        "Reelo, one row per store that is on the file. Missing stores are intentional.",
        _lines(
            [
                {
                    "store": row.get("store"),
                    "phone_capture_pct": _num(row.get("phone_capture"), 2),
                    "repeat_share_pct": _num(row.get("repeat_share"), 2),
                }
                for row in (data.get("reelo") or [])
            ],
            ["store", "phone_capture_pct", "repeat_share_pct"],
        ),
        "",
        _tickets_block(data.get("tickets") or {}),
        "",
        _prices_block(data.get("procurement") or {}, question),
        "",
        _food_block(data),
    ]
    if role in {"owner", "finance"} and data.get("finance"):
        parts.extend(["", "Finance (this role may see it):", _lines(data.get("finance") or [], ["kicker", "label", "value"])])
    else:
        parts.extend(["", "Finance: not included for this role."])
    if role in {"owner", "hr"}:
        people = []
        for row in (data.get("dossiers") or {}).values():
            hr = row.get("hr") or {}
            if hr.get("lead") or hr.get("headcount"):
                people.append({"store": row.get("name"), "lead": hr.get("lead") or "", "headcount": hr.get("headcount") or ""})
        parts.extend(["", "People (this role may see it):", _lines(people, ["store", "lead", "headcount"])])
    else:
        parts.extend(["", "People: not included for this role."])
    parts.append("")
    parts.extend(_delivery_note(question))
    parts.extend(_licence_note(question, role))
    from app.chat.menu_hr import hr_packet, menu_packet

    menu = menu_packet(question)
    if menu:
        parts.extend(["", menu])
    people = hr_packet(question, role)
    if people:
        parts.extend(["", people])
    parts.append("")
    from app.chat.wizard_a import domain_text

    extra = domain_text(question, role)
    if extra:
        parts.extend(["", extra])
    parts.append("")
    parts.append(
        "If a figure the question needs is not in this packet, say so plainly and answer the closest question this packet can support."
    )
    return _fit("\n".join(parts))


def _fit(text, limit_tokens=12000):
    """Keep the prompt near 12k tokens. The sales rows sit at the front and stay."""
    limit = limit_tokens * 4
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated to stay within the prompt budget]"


def _delivery_note(question):
    from app.chat.facts import _asks_delivery_economics
    from app.commercial import basis_sentence, payout_files

    if not _asks_delivery_economics(question):
        return []
    files = payout_files()
    loaded = ", ".join(path.name for path in files[:4]) if files else "none loaded"
    return [
        "",
        "Delivery economics:",
        basis_sentence(),
        f"Payout or ads files: {loaded}. Prefer an actual payout over the 24.78% rule and show the gap. Do not apply the rule to dine-in, takeaway, or to gross.",
    ]


def _licence_note(question, role):
    from app.chat.licences import packet, relevant

    if not relevant(question):
        return []
    body = packet(question, role)
    if not body:
        return ["", "Licences: not included for this role."]
    return ["", body]


def _summary_line(summary):
    if not summary:
        return "No network summary is loaded."
    bits = []
    if summary.get("target_pace_pct") is not None:
        bits.append(f"target pace {summary.get('target_pace_pct')}%")
    if summary.get("mtd_actual_L") is not None:
        bits.append(f"month-to-date net {summary.get('mtd_actual_L')} Lakh")
    if summary.get("mtd_pred_mid_L") is not None:
        bits.append(f"mid forecast {summary.get('mtd_pred_mid_L')} Lakh")
    regions = summary.get("regional_mtd") if isinstance(summary.get("regional_mtd"), dict) else {}
    for name, row in regions.items():
        if isinstance(row, dict) and row.get("pace_pct") is not None:
            bits.append(f"{name} pace {row.get('pace_pct')}%")
    return "; ".join(bits) if bits else "Summary file is loaded but has no pace figures."


def _tickets_block(tickets):
    if not tickets or not tickets.get("stores"):
        return "Famepilot tickets: not loaded."
    lines = [
        f"Famepilot tickets. Newest ticket date: {tickets.get('as_of') or 'unknown'}."
        + (" This is more than 7 days old." if tickets.get("older_than_7") else ""),
        "Stale means the ticket keyword is Stale. Share is a percent of that store's tickets.",
    ]
    rows = []
    for row in tickets.get("stores") or []:
        channels = row.get("channels") or {}
        rows.append({
            "store": row.get("store"),
            "tickets": row.get("count"),
            "stale": row.get("stale"),
            "stale_share_pct": row.get("stale_share"),
            "zomato": (channels.get("zomato") or {}).get("tickets") or 0,
            "swiggy": (channels.get("swiggy") or {}).get("tickets") or 0,
        })
    rows.sort(key=lambda row: row.get("stale") or 0, reverse=True)
    lines.append(_lines(rows, ["store", "tickets", "stale", "stale_share_pct", "zomato", "swiggy"]))
    return "\n".join(lines)


def _prices_block(pack, question):
    if not pack:
        return "Procurement prices: not loaded."
    folded = (question or "").casefold()
    lines = [
        f"Procurement summary as_of {pack.get('as_of') or 'unknown'}. Compare a city only with its own last month or its own baseline.",
        "Bought above each city's own baseline in the last 7 days:",
    ]
    above = []
    for row in pack.get("above_average") or []:
        if not isinstance(row, dict):
            continue
        above.append({
            "city": row.get("city"),
            "item": row.get("item"),
            "price": row.get("price"),
            "baseline": row.get("baseline_avg"),
            "pct_above": row.get("pct_above"),
            "date": row.get("date"),
        })
    lines.append(_lines(above, ["city", "item", "price", "baseline", "pct_above", "date"]))
    items = ((pack.get("monthly_prices") or {}).get("items") or []) if isinstance(pack.get("monthly_prices"), dict) else []
    wanted = [word for word in ("milk", "paneer", "cheese", "food") if word in folded]
    picked = []
    for row in items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("item") or "").casefold()
        if wanted and not any(word in name for word in wanted):
            continue
        if not wanted and len(picked) >= 12:
            break
        this = (row.get("this_month") or {}).get("avg_unit_price") if isinstance(row.get("this_month"), dict) else None
        last = (row.get("last_month") or {}).get("avg_unit_price") if isinstance(row.get("last_month"), dict) else None
        picked.append({
            "city": row.get("city"),
            "item": row.get("item"),
            "this_month": this,
            "last_month": last,
            "pct_change": row.get("pct_change"),
        })
        if wanted and len(picked) >= 24:
            break
    lines.append("Monthly average unit price, this month versus last month, each city against itself:")
    lines.append(_lines(picked, ["city", "item", "this_month", "last_month", "pct_change"]))
    return "\n".join(lines)


def _food_block(data):
    rows = []
    period = ""
    for row in (data.get("dossiers") or {}).values():
        food = row.get("food") or {}
        if food.get("pct") is None and not food.get("text") and not food.get("sanity") and not food.get("total_pct"):
            continue
        period = period or food.get("period") or ""
        rows.append({
            "store": row.get("name") or food.get("name"),
            "food_cost_pct": "" if food.get("sanity") else (food.get("text") or food.get("pct") or ""),
            "packaging_pct": food.get("packaging_pct") or "",
            "total_incl_packaging_pct": food.get("total_pct") or "",
            "raw": food.get("raw") or "",
            "semi": food.get("semi") or "",
            "packaging": food.get("other") or "",
            "gross": food.get("gross") or "",
            "city_median": "" if food.get("exclude_compare") else (food.get("city_median") or ""),
            "note": food.get("sanity") or food.get("basis") or "",
        })
    if not rows:
        return "Food cost: no store food-cost percent is loaded. Do not invent one. The closest figures are the procurement prices above."
    rows.sort(key=lambda row: row.get("store") or "")
    return (
        "Food cost percent by store"
        + (f" ({period})" if period else "")
        + ". Food cost is (raw + semi-processed consumption) / Posist gross. "
        "Packaging/other is separate. Total includes packaging. Raw-only is not food cost. "
        "Under 15% or over 45% is not stated as fact. Faridabad is out of comparisons. "
        "Each city is compared with its own median. NCR is higher by design (3 chutneys).\n"
        + _lines(
            rows,
            [
                "store", "food_cost_pct", "packaging_pct", "total_incl_packaging_pct",
                "raw", "semi", "packaging", "gross", "city_median", "note",
            ],
        )
    )
