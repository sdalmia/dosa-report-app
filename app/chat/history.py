"""Month-by-month figures for the Wizard, from 1 Apr 2026.

The prompt only gets a short coverage line. Figures for a named month come
from lookup() or the month_lookup tool, so the prompt stays within budget.
A missing month is stated plainly, with who the data would come from.
No figure is invented or estimated.
"""

from __future__ import annotations

import csv
import json
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.chat.month_sales import _lakh, _MONTH_LABEL, _MONTHS, _MONTH_SHORT

_ROOT = Path(__file__).resolve().parents[2]
_HISTORY = _ROOT / "data" / "history"
_WINDOW_START = date(2026, 4, 1)
_WINDOW_END = date(2026, 11, 13)

# Who would supply a month that is not loaded. Used in the missing-month answer.
_OWNERS = {
    "sales": ("Alfred", "who pulls Posist Insights daily sales", "sales"),
    "channel": ("Alfred", "who pulls Posist Insights channel sales", "channel sales"),
    "procurement": ("Procurement", "who pulls the PurchaseEasy reports", "procurement figures"),
    "menu_mix": ("Jarvis", "who pulls the Posist menu-mix extracts", "menu-mix figures"),
    "reelo": ("Logan", "who pulls the Reelo dashboard exports", "Reelo figures"),
    "wastage": ("Procurement", "who pulls the PurchaseEasy wastage reports", "wastage figures"),
    "consumption": ("Procurement", "who pulls the PurchaseEasy consumption reports", "consumption figures"),
    "aggregator": ("Sanjoy", "who maintains the brand aggregator workbook", "aggregator figures"),
    "finance": ("Shilajit", "who sends the Grand Economics workbook", "Grand Economics figures"),
    "tally": ("the Accountant", "who sends the daily Tally Day Book packs (via Shilajit)", "Tally figures"),
    "hr": ("the HR Bot", "who pulls the Keka aggregates", "HR counts"),
    "famepilot": ("Albus", "who pulls the Famepilot ticket export", "Famepilot ticket counts"),
}

_OWNER_ONLY = {
    "finance": {"owner", "finance"},
    "tally": {"owner", "finance"},
    "hr": {"owner"},
}

_DOMAIN_WORDS = {
    "sales": ("sale", "sales", "sold", "gross", "revenue", "turnover"),
    "channel": ("channel", "dine-in", "dine in", "dinein", "takeaway", "takeout", "swiggyonline", "zomatoonline", "ondc", "pos sale"),
    "procurement": ("procurement", "purchase", "grn", "vendor", "ingredient price", "unit price"),
    "wastage": ("wastage", "waste %", "stock wastage", "billing wastage"),
    "consumption": ("consumption", "food cost", "consumption vs recipe", "recipe vs consumption"),
    "menu_mix": ("menu mix", "menu-mix", "best sell", "item sales", "contribution"),
    "reelo": ("reelo", "loyalty", "repeat customer", "new customer", "phone capture"),
    "aggregator": ("aggregator", "swiggy", "zomato", "offline hour", "ad spend", "impressions"),
    "finance": ("grand economics", "p&l", "p and l", "ebitda", "fnb cost", "net revenue"),
    "tally": ("tally", "day book", "daybook", "voucher"),
    "hr": ("headcount", "joiners", "exits", "attrition", "hr count"),
    "famepilot": ("famepilot", "ticket"),
}

# Questions that should not be taken as a sales-month lookup.
_SKIP_SALES = (
    "audit", "mystery", "licence", "license", "budget", "inventory",
    "recipe", "ebitda", "grand economics", "tally", "day book", "daybook",
    "headcount", "employee", "swiggy", "zomato", "aggregator",
    "food cost", "consumption",
)


def _num(value):
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "").replace("₹", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _dec(value):
    number = _num(value)
    if number is None:
        return None
    return Decimal(str(number))


def _inr_plain(value):
    if value is None:
        return "not in the file"
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}₹{abs(number):,.2f}"


def load_coverage():
    path = _HISTORY / "coverage.json"
    if not path.is_file():
        return {"domains": [], "window_start": "2026-04-01", "window_end": "2026-11-13", "as_of": "2026-11-13"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"domains": [], "window_start": "2026-04-01", "window_end": "2026-11-13", "as_of": "2026-11-13"}


def _domains(role="ops"):
    coverage = load_coverage()
    out = []
    for domain in coverage.get("domains") or []:
        roles = set(domain.get("roles") or ["owner", "ops", "finance", "hr"])
        if role not in roles:
            continue
        out.append(domain)
    return out


def domain_record(domain_id, role="ops"):
    for domain in _domains(role):
        if domain.get("id") == domain_id:
            return domain
    # Still return the record for missing-month wording when the role may see it
    for domain in load_coverage().get("domains") or []:
        if domain.get("id") == domain_id:
            return domain
    return None


def month_loaded(domain_id, year, month, role="ops"):
    record = domain_record(domain_id, role)
    if record is None:
        return False
    key = f"{year:04d}-{month:02d}"
    return key in (record.get("months_loaded") or [])


def _month_named(folded):
    found = []
    for name, month in _MONTHS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", folded):
            found.append((len(name), month))
    if not found:
        match = re.search(r"\b(20\d{2})-(\d{2})\b", folded)
        if match:
            return int(match.group(2)), int(match.group(1))
        return None, None
    found.sort(reverse=True)
    month = found[0][1]
    year_match = re.search(r"\b(20\d{2})\b", folded)
    year = int(year_match.group(1)) if year_match else 2026
    return month, year


def _detect_domain(folded):
    """Most specific domain mentioned. Aggregator beats generic sales words."""
    finance_markers = ("grand economics", "p&l", "p and l", "ebitda", "fnb cost")
    if ("wastage" in folded or "waste %" in folded or "stock wastage" in folded) and not any(
        token in folded for token in finance_markers
    ):
        return "wastage"
    if (
        any(token in folded for token in ("food cost", "consumption", "consumption vs recipe", "recipe vs consumption"))
        and not any(token in folded for token in finance_markers)
        and "wastage" not in folded
        and "waste %" not in folded
    ):
        return "consumption"
    hits = []
    for domain_id, words in _DOMAIN_WORDS.items():
        for word in words:
            if word in folded:
                hits.append((len(word), domain_id))
                break
    if not hits:
        return None
    hits.sort(reverse=True)
    # Swiggy/Zomato vs Famepilot tickets: "ticket" + platform is famepilot;
    # "swiggy vs zomato" without ticket is aggregator.
    ids = {item[1] for item in hits}
    if "aggregator" in ids and "famepilot" in ids:
        if "ticket" in folded or "famepilot" in folded:
            return "famepilot"
        return "aggregator"
    if "aggregator" in ids:
        return "aggregator"
    return hits[0][1]


def coverage_line(role="ops"):
    """A compact paragraph for the prompt. Details stay in the lookup tool."""
    coverage = load_coverage()
    start = coverage.get("window_start") or "2026-04-01"
    end = coverage.get("window_end") or "2026-11-13"
    as_of = coverage.get("as_of") or end
    lines = [
        f"History coverage ({_short(start)} to {_short(end)}, as of {_short(as_of)}). "
        "Use the month_lookup tool for a named month's figures so this prompt stays short. "
        "When a month is not loaded, say the data is not loaded yet and name who it would come from. "
        "Never estimate a missing month.",
    ]
    bits = []
    for domain in _domains(role):
        loaded = domain.get("months_loaded") or []
        missing = domain.get("months_missing") or []
        loaded_txt = _month_list(loaded) or "none"
        missing_txt = _month_list(missing)
        piece = f"{domain.get('label') or domain['id']} ({domain.get('owner')}): loaded {loaded_txt}"
        if domain.get("from") and domain.get("to"):
            piece += f", { _short(domain['from'])}–{_short(domain['to'])}"
        if missing_txt:
            piece += f". Not loaded: {missing_txt}"
        bits.append(piece + ".")
    if bits:
        lines.extend(bits)
    else:
        lines.append("No history coverage file is loaded.")
    return "\n".join(lines)


def _short(iso):
    text = str(iso or "")
    try:
        if len(text) == 7:
            year, month = int(text[:4]), int(text[5:7])
            return f"{_MONTH_SHORT[month]} {year}"
        day = datetime.strptime(text[:10], "%Y-%m-%d").date()
        return f"{day.day} {_MONTH_SHORT[day.month]} {day.year}"
    except (ValueError, IndexError):
        return text


def _month_list(months):
    labels = []
    for key in months:
        try:
            year, month = int(key[:4]), int(key[5:7])
            labels.append(f"{_MONTH_SHORT[month]} {year}")
        except (ValueError, IndexError):
            labels.append(key)
    return ", ".join(labels)


def _label(year, month):
    return f"{_MONTH_LABEL[month]} {year}"


def missing_text(domain_id, year, month):
    """Plain wording for a month we do not have. Never includes a figure."""
    label = _label(year, month)
    who, how, noun = _OWNERS.get(domain_id, ("the owner of that domain", "when the file is sent", "figures"))
    if domain_id == "sales":
        return (
            f"{label} sales are not in the loaded daily files. "
            f"That month would come from {who}, {how}. No figure is invented."
        )
    return (
        f"{label} {noun} are not loaded yet. "
        f"That month would come from {who}, {how}. No figure is invented."
    )


def _read_csv(*parts):
    """Read a history CSV and any matching extra/ drop with the same name."""
    rows = []
    names = parts if parts else []
    for name in names:
        paths = [_HISTORY / name, _HISTORY / "extra" / name]
        for path in paths:
            if not path.is_file():
                continue
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows.extend(list(csv.DictReader(handle)))
    return rows


def _allowed(domain_id, role):
    allowed = _OWNER_ONLY.get(domain_id)
    if allowed is None:
        return True
    return role in allowed


def _role_denied(domain_id):
    if domain_id == "hr":
        return "HR figures are not included for this role."
    if domain_id in {"finance", "tally"}:
        return "Finance and Tally figures are not included for this role."
    return "That domain is not included for this role."


def _filter_month(rows, year, month):
    key = f"{year:04d}-{month:02d}"
    return [row for row in rows if (row.get("month") or "") == key]


def _city_from_question(folded):
    if any(token in folded for token in ("kolkata", "calcutta", "east")):
        return "Kolkata"
    if any(token in folded for token in ("ncr", "delhi", "north", "gurgaon", "noida", "faridabad")):
        return "NCR"
    return ""


def _answer_sales(year, month, question, role):
    if not month_loaded("sales", year, month, role):
        return missing_text("sales", year, month)
    rows = _filter_month(_read_csv("sales_city_month.csv"), year, month)
    if not rows:
        return missing_text("sales", year, month)
    city = _city_from_question((question or "").casefold())
    label = _label(year, month)
    source = "Posist daily files"
    if any("monthly extract" in (row.get("note") or "") for row in rows):
        source = "Alfred's Posist Insights monthly extract"
    elif any("Full calendar September" in (row.get("note") or "") for row in rows):
        source = "Alfred's Posist Insights extract for 1–3 Sep and Posist daily files for 4–30 Sep"
    fb = (
        "Faridabad is included (it is in the sales base until 22 Oct)"
        if (year, month) < (2026, 10)
        else "Faridabad is out of the sales base from 23 Oct"
    )
    lines = [
        f"{label} sales, from {source} "
        f"(Chattarpur and GK1 out of the sales base; {fb}). "
        "Net is left blank when the file has none, not treated as zero."
    ]
    # Events is its own city row, counted in the network total, out of store comparisons.
    events = [row for row in rows if (row.get("city") or "").casefold() == "events"]
    cities = [row for row in rows if (row.get("city") or "").casefold() != "events"]
    picked = [row for row in cities if not city or row.get("city") == city]
    if city and city.casefold() == "events":
        picked = events
    if city and not picked and city.casefold() != "events":
        return f"{city} {label} sales are not in the loaded daily files. That month would come from Alfred, who pulls Posist Insights daily sales. No figure is invented."
    network_gross = sum((_dec(r.get("gross")) or 0) for r in rows)
    # bills: city file has bills_ex_mall. Network bills that match Alfred are the raw sum including mall and Events, from the store file.
    stores = _filter_month(_read_csv("sales_store_month.csv"), year, month)
    raw_bills = sum((_dec(r.get("bills")) or 0) for r in stores if r.get("bills") not in (None, ""))
    if not city:
        bills_txt = f", {int(raw_bills):,} bills" if raw_bills else ""
        lines.append(f"Network: {_lakh(network_gross)} gross{bills_txt}.")
    for row in picked:
        note = row.get("note") or ""
        complete = "complete" if row.get("complete") == "yes" else "incomplete"
        span = f"{row.get('first_day')} to {row.get('last_day')}"
        mall = ""
        if _num(row.get("mall_gross")):
            mall = (
                f" That includes Manisquare and Forum sales of {_lakh(_num(row['mall_gross']))}. "
                "Mall bulk bills and average bill stay out of comparisons; their sales are counted."
            )
        bills = row.get("bills_ex_mall") or ""
        bills_txt = f", {int(float(bills)):,} bills excluding mall bulk" if _num(bills) else ""
        net = row.get("net") or ""
        net_txt = f" Net {_lakh(_num(net))}." if _num(net) else " Net is blank in the file."
        lines.append(
            f"{row.get('city')}: {_lakh(_num(row['gross']))} gross{bills_txt}, {complete}, {span} "
            f"({row.get('days_present')} of {row.get('days_in_month')} days).{mall}{net_txt} {note}".strip()
        )
    if events and not city:
        ev = events[0]
        lines.append(
            f"Events & Catering: {_lakh(_num(ev['gross']))} gross "
            f"({ev.get('first_day')} to {ev.get('last_day')}), counted in the network total "
            "and kept as its own row, outside store comparisons."
        )
    # A short store table (mall bills as em dash), Events excluded from comparisons.
    show_stores = [r for r in stores if (not city or r.get("city") == city) and (r.get("city") or "").casefold() != "events"]
    if show_stores:
        show_stores = sorted(show_stores, key=lambda r: _num(r.get("gross")) or 0, reverse=True)
        lines.append("store | city | gross | bills | days")
        for row in show_stores[:16]:
            bills = "—" if row.get("mall_bulk") == "yes" else (
                f"{int(float(row['bills'])):,}" if _num(row.get("bills")) is not None else ""
            )
            lines.append(
                f"{row.get('store')} | {row.get('city')} | {_lakh(_num(row['gross']))} | {bills} | "
                f"{row.get('days_present')} of {row.get('days_in_month')}"
            )
    lines.append("No missing day is treated as zero.")
    return "\n".join(lines)


def _answer_channel(year, month, question, role):
    if not month_loaded("channel", year, month, role):
        return missing_text("channel", year, month)
    rows = _filter_month(_read_csv("channel_store_month.csv"), year, month)
    if not rows:
        return missing_text("channel", year, month)
    city = _city_from_question((question or "").casefold())
    label = _label(year, month)
    totals = defaultdict(lambda: {"sales": Decimal(0), "orders": Decimal(0)})
    note = ""
    first, last = None, None
    for row in rows:
        if city and row.get("city") != city:
            continue
        source = row.get("source") or "unknown"
        sales = _dec(row.get("sales")) or Decimal(0)
        orders = _dec(row.get("orders")) or Decimal(0)
        totals[source]["sales"] += sales
        totals[source]["orders"] += orders
        if row.get("note"):
            note = row["note"]
        for edge, key in ((min, "first_day"), (max, "last_day")):
            day = row.get(key)
            if not day:
                continue
            if key == "first_day":
                first = day if first is None else min(first, day)
            else:
                last = day if last is None else max(last, day)
    if not totals:
        where = f"{city} " if city else ""
        return f"{where}{label} channel sales are not loaded yet. That month would come from Alfred, who pulls Posist Insights channel sales. No figure is invented."
    lines = [
        f"{label} channel sales{(' for ' + city) if city else ''}, from Posist channel files, {first} to {last}.",
    ]
    for source, bucket in sorted(totals.items(), key=lambda kv: kv[1]["sales"], reverse=True):
        lines.append(f"{source}: {_lakh(bucket['sales'])} ({int(bucket['orders'])} orders).")
    if note:
        lines.append(note)
    lines.append("A missing day is left out, not treated as zero.")
    return "\n".join(lines)


def _answer_aggregator(year, month, question, role):
    if not month_loaded("aggregator", year, month, role):
        return missing_text("aggregator", year, month)
    rows = _filter_month(_read_csv("aggregator_store_month.csv"), year, month)
    if not rows:
        return missing_text("aggregator", year, month)
    label = _label(year, month)
    city = _city_from_question((question or "").casefold())
    # Workbook region is "Delhi NCR" / "Kolkata"
    def match_city(row):
        if not city:
            return True
        region = (row.get("region") or "").casefold()
        if city == "Kolkata":
            return "kolkata" in region
        return "ncr" in region or "delhi" in region

    acc = defaultdict(lambda: {"sales": Decimal(0), "orders": Decimal(0), "n": 0, "ads_blank": 0, "impr_blank": 0})
    unmapped = sorted({row.get("workbook_name") for row in rows if row.get("match_status") == "unmapped"})
    for row in rows:
        if not match_city(row):
            continue
        platform = row.get("platform") or ""
        region = row.get("region") or ""
        sales = _dec(row.get("net_sales"))
        orders = _dec(row.get("orders"))
        for key in (platform, platform + "|" + region, "ALL"):
            if sales is not None and key != "ALL" or key == "ALL":
                pass
        if sales is not None:
            acc[platform]["sales"] += sales
            acc[platform + "|" + region]["sales"] += sales
        if orders is not None:
            acc[platform]["orders"] += orders
        acc[platform]["n"] += 1
        if row.get("ad_spend") == "":
            acc[platform]["ads_blank"] += 1
        if row.get("impressions") == "":
            acc[platform]["impr_blank"] += 1
    if not acc:
        return missing_text("aggregator", year, month)
    outlets = acc.get("Zomato", acc.get("Swiggy", {})).get("n") or 0
    lines = [
        f"{label} Swiggy vs Zomato, from Sanjoy's aggregator workbook "
        f"({outlets} outlets in these totals; Faridabad Sector 15 is left out). "
        "Figures are net sales as in the file.",
        "",
    ]
    for platform in ("Zomato", "Swiggy"):
        bucket = acc.get(platform)
        if not bucket:
            continue
        sales_txt = _lakh(bucket["sales"]) if bucket["sales"] else "not in the file"
        orders_txt = f"{int(bucket['orders'])} orders" if bucket["orders"] else "orders not in the file"
        extra = ""
        if platform == "Zomato":
            extra = " Zomato actuals are complete, including impressions, ads and refunds."
        else:
            extra = (
                " Swiggy impressions, ads and refunds are blank in the workbook (still pending). "
                "Those cells are left blank, not treated as zero."
            )
        lines.append(f"{platform} net sales: {sales_txt} ({orders_txt}).{extra}")
        for region in ("Kolkata", "Delhi NCR"):
            sub = acc.get(platform + "|" + region)
            if sub and sub["sales"]:
                lines.append(f"  {region}: {_lakh(sub['sales'])}.")
        lines.append("")
    if unmapped:
        lines.append(
            "Outlet names are mapped to store-master names where the match is clear; "
            + ", ".join(unmapped)
            + " are left under the workbook names."
        )
    lines.append("No figure is estimated for a blank cell.")
    return "\n".join(lines)


def _answer_procurement(year, month, question, role):
    if not month_loaded("procurement", year, month, role):
        return missing_text("procurement", year, month)
    label = _label(year, month)
    folded = (question or "").casefold()
    lines = [f"{label} procurement, from the loaded PurchaseEasy / procurement files."]
    # prices
    prices = _filter_month(_read_csv("prices_item_month.csv"), year, month)
    if prices and any(token in folded for token in ("price", "ingredient", "unit")) or (prices and "vendor" not in folded):
        if prices:
            by_city = defaultdict(int)
            complete_row = next((r for r in prices if r.get("complete") == "yes"), prices[0])
            note = complete_row.get("note") or ""
            complete = complete_row.get("complete")
            for row in prices:
                by_city[row.get("city") or ""] += 1
            lines.append(
                f"Item prices: {sum(by_city.values())} item-city rows, "
                f"{'complete' if complete == 'yes' else 'incomplete'}. {note}"
            )
            # Rank by purchase value so unit-scale items (napkins, spices in grams)
            # do not crowd out the larger spends.
            def _value(r):
                qty = _num(r.get("qty")) or 0
                price = _num(r.get("avg_unit_price")) or 0
                return qty * price
            ranked = sorted(prices, key=_value, reverse=True)
            lines.append("city | item | avg unit price | qty")
            for row in ranked[:8]:
                price = row.get("avg_unit_price") or "not in the file"
                lines.append(f"{row.get('city')} | {row.get('item')} | {price} | {row.get('qty') or ''}")
    purchases = _filter_month(_read_csv("purchases_vendor_month.csv"), year, month)
    items = _filter_month(_read_csv("purchases_item_month.csv"), year, month)
    if purchases or items:
        total = sum((_dec(r.get("total")) or 0) for r in purchases)
        complete_row = next((r for r in (purchases or items) if r.get("complete") == "yes"), None)
        note = (complete_row or (purchases or items)[0]).get("note") or ""
        lines.append(
            f"Purchases: {_lakh(total)} across {len(purchases)} vendor-warehouse rows, "
            f"{len(items)} item rows. {note}"
        )
        ranked = sorted(purchases, key=lambda r: _num(r.get("total")) or 0, reverse=True)
        lines.append("city | vendor | total")
        for row in ranked[:8]:
            lines.append(f"{row.get('city')} | {row.get('vendor')} | {_lakh(_num(row.get('total')))}")
    elif not prices:
        return missing_text("procurement", year, month)
    else:
        if month_loaded("procurement", year, month, role) and not purchases:
            lines.append(
                "Purchase (GRN) lines for this month are not on file. "
                "Only item prices are loaded. No purchase total is invented."
            )
    return "\n".join(lines)


def _answer_menu(year, month, question, role):
    if not month_loaded("menu_mix", year, month, role):
        return missing_text("menu_mix", year, month)
    rows = _filter_month(_read_csv("menu_item_month.csv"), year, month)
    if not rows:
        return missing_text("menu_mix", year, month)
    label = _label(year, month)
    city = _city_from_question((question or "").casefold())
    # Filter roughly by city tokens in store name
    def in_city(store):
        if not city:
            return True
        text = (store or "").casefold()
        north = any(tok in text for tok in ("noida", "gurgaon", "faridabad", "kalkaji", "rohini", "connaught", "paschim", "shalimar", "model town", "jasola", "pacific", "02/", "sec 15", "sec 18", "sec 31", "sec 143", "huda"))
        if city == "NCR":
            return north
        return not north

    picked = [row for row in rows if in_city(row.get("store"))]
    totals = defaultdict(lambda: {"sales": Decimal(0), "orders": Decimal(0)})
    for row in picked:
        item = row.get("item") or ""
        sales = _dec(row.get("total_sales")) or Decimal(0)
        orders = _dec(row.get("total_orders")) or Decimal(0)
        totals[item]["sales"] += sales
        totals[item]["orders"] += orders
    ranked = sorted(totals.items(), key=lambda kv: kv[1]["sales"], reverse=True)
    note = (picked[0].get("note") if picked else "") or ""
    span = ""
    if picked:
        span = f"{picked[0].get('period_start')} to {picked[0].get('period_end')}"
    where = f" for {city}" if city else ""
    lines = [
        f"{label} menu mix{where}, calendar month {span}. {note}".strip(),
        "item | sales | orders",
    ]
    for item, bucket in ranked[:12]:
        lines.append(f"{item} | {_lakh(bucket['sales'])} | {int(bucket['orders'])}")
    lines.append(f"{len(picked)} item-store rows in the file. No missing store is filled with zero.")
    return "\n".join(lines)


def _answer_reelo(year, month, question, role):
    if not month_loaded("reelo", year, month, role):
        return missing_text("reelo", year, month)
    rows = _filter_month(_read_csv("reelo_month.csv"), year, month)
    if not rows:
        return missing_text("reelo", year, month)
    row = rows[0]
    label = _label(year, month)
    lines = [f"{label} Reelo, network totals from {row.get('source') or 'the Reelo monthly export'}. Period: {row.get('period_label') or label}."]
    mapping = [
        ("customers", "Customers"),
        ("new_customers", "New customers"),
        ("repeat_customers", "Repeat customers"),
        ("total_orders", "Total orders"),
        ("new_orders", "New orders"),
        ("repeat_orders", "Repeat orders"),
        ("overall_aov", "Overall AOV (₹)"),
        ("apc", "APC (₹)"),
    ]
    for key, title in mapping:
        val = row.get(key)
        if val not in (None, ""):
            lines.append(f"{title}: {val}")
        elif key in ("total_orders", "overall_aov") and (row.get("complete") == "no"):
            lines.append(f"{title}: not in the monthly file for this incomplete month. No figure is invented.")
    if row.get("note"):
        lines.append(row["note"])
    if row.get("complete") == "no":
        lines.append("This month is incomplete.")
    return "\n".join(lines)


def _answer_finance(year, month, question, role):
    if not _allowed("finance", role):
        return _role_denied("finance")
    if not month_loaded("finance", year, month, role):
        return missing_text("finance", year, month)
    rows = _filter_month(_read_csv("finance_city_month.csv"), year, month)
    if not rows:
        return missing_text("finance", year, month)
    folded = (question or "").casefold()
    city = _city_from_question(folded)
    wanted = [line for line in (
        "ebitda", "fnb_cost", "gross_revenue", "net_revenue", "rent", "salary",
        "ads", "purchases", "electricity", "gas", "commission", "wastage",
    ) if line.replace("_", " ") in folded or line in folded]
    if "food cost" in folded:
        wanted.append("fnb_cost")
    if not wanted:
        wanted = ["gross_revenue", "net_revenue", "fnb_cost", "rent", "salary", "ads", "ebitda"]
    label = _label(year, month)
    lines = [
        f"{label} Grand Economics, city-level lines from grand_economics_tidy.csv. "
        "NCR recipe cost is higher by design (3 chutneys versus 1). Compare a city only with itself.",
        "city | line | value",
    ]
    count = 0
    for row in rows:
        if city and row.get("city") != city:
            continue
        if wanted and (row.get("line") or "") not in wanted:
            continue
        value = _num(row.get("value"))
        shown = _lakh(value) if value is not None else (row.get("value") or "")
        lines.append(f"{row.get('city')} | {row.get('line')} | {shown}")
        count += 1
    if count == 0:
        return missing_text("finance", year, month)
    if month >= 2026 and month in (8, 9) or True:
        if month in (8, 9) and year == 2026:
            lines.append("August and September Kolkata advertising was booked in October, so those months understate ads.")
    return "\n".join(lines)


def _answer_tally(year, month, question, role):
    if not _allowed("tally", role):
        return _role_denied("tally")
    if not month_loaded("tally", year, month, role):
        return missing_text("tally", year, month)
    rows = _filter_month(_read_csv("tally_company_month.csv"), year, month)
    if not rows:
        return missing_text("tally", year, month)
    label = _label(year, month)
    lines = [
        f"{label} Tally day-book totals, by company and voucher type. "
        "Missing days are left out, not filled with zero.",
        "company | type | vouchers | total | days present",
    ]
    for row in sorted(rows, key=lambda r: (r.get("company") or "", r.get("type_group") or "")):
        total = _num(row.get("total_amt"))
        lines.append(
            f"{row.get('company')} | {row.get('type_group')} | {row.get('voucher_count')} | "
            f"{_lakh(total) if total is not None else ''} | "
            f"{row.get('days_present')} of {row.get('days_in_month')} ({row.get('first_day')} to {row.get('last_day')})"
        )
    if rows and rows[0].get("note"):
        lines.append(rows[0]["note"])
    return "\n".join(lines)


def _answer_hr(year, month, question, role):
    if not _allowed("hr", role):
        return _role_denied("hr")
    if not month_loaded("hr", year, month, role):
        return missing_text("hr", year, month)
    rows = _filter_month(_read_csv("hr_month.csv"), year, month)
    if not rows:
        return missing_text("hr", year, month)
    label = _label(year, month)
    joiners = sum(int(_num(r.get("joiners")) or 0) for r in rows)
    exits = sum(int(_num(r.get("exits")) or 0) for r in rows)
    lines = [
        f"{label} HR counts, location-level, no names. "
        + (rows[0].get("note") or "Counts only."),
        f"Network: {joiners} joiners, {exits} exits across {len(rows)} locations.",
        "location | joiners | exits | absconded | resigned | company action",
    ]
    ranked = sorted(rows, key=lambda r: (int(_num(r.get("exits")) or 0), int(_num(r.get("joiners")) or 0)), reverse=True)
    for row in ranked:
        if int(_num(row.get("joiners")) or 0) == 0 and int(_num(row.get("exits")) or 0) == 0:
            continue
        lines.append(
            f"{row.get('location')} | {row.get('joiners')} | {row.get('exits')} | "
            f"{row.get('exits_absconded')} | {row.get('exits_resigned')} | {row.get('exits_company_action')}"
        )
    lines.append("Locations with 0 joiners and 0 exits are real zero counts and are not listed above.")
    return "\n".join(lines)


def _answer_famepilot(year, month, question, role):
    if not month_loaded("famepilot", year, month, role):
        return missing_text("famepilot", year, month)
    rows = _filter_month(_read_csv("famepilot_tickets_month.csv"), year, month)
    if not rows:
        return missing_text("famepilot", year, month)
    label = _label(year, month)
    total = sum(int(r.get("tickets") or 0) for r in rows)
    stale = sum(int(r.get("stale") or 0) for r in rows)
    by_plat = defaultdict(int)
    for row in rows:
        by_plat[row.get("platform") or "unknown"] += int(row.get("tickets") or 0)
    lines = [
        f"{label} Famepilot ticket counts (no customer names). {rows[0].get('note') or ''}".strip(),
        f"Total tickets: {total}. Stale: {stale}.",
    ]
    for platform, count in sorted(by_plat.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"{platform}: {count}.")
    ranked = sorted(rows, key=lambda r: int(r.get("tickets") or 0), reverse=True)
    lines.append("store | platform | tickets | stale")
    for row in ranked[:12]:
        lines.append(f"{row.get('store')} | {row.get('platform')} | {row.get('tickets')} | {row.get('stale')}")
    return "\n".join(lines)



def _answer_wastage(year, month, question, role):
    if not month_loaded("wastage", year, month, role):
        return missing_text("wastage", year, month)
    stores = _filter_month(_read_csv("wastage_store_month.csv"), year, month)
    items = _filter_month(_read_csv("wastage_item_month.csv"), year, month)
    if not stores and not items:
        return missing_text("wastage", year, month)
    city = _city_from_question((question or "").casefold())
    if city:
        stores = [r for r in stores if r.get("city") == city]
        items = [r for r in items if r.get("city") == city]
        if not stores and not items:
            return missing_text("wastage", year, month)
    label = _label(year, month)
    note = (stores or items)[0].get("note") or ""
    complete = (stores or items)[0].get("complete")
    first = (stores or items)[0].get("first_day") or ""
    last = (stores or items)[0].get("last_day") or ""
    total = sum((_dec(r.get("total_wastage_amt")) or 0) for r in stores)
    stock = sum((_dec(r.get("stock_wastage_amt")) or 0) for r in stores)
    billing = sum((_dec(r.get("billing_wastage_amt")) or 0) for r in stores)
    lines = [
        f"{label} wastage, from the PurchaseEasy wastage extracts, {first} to {last}"
        f"{' (incomplete)' if complete != 'yes' else ' (complete)'}. {note}",
        f"Total wastage: {_lakh(total)} across {len(stores)} deployments, {len(items)} item rows. "
        f"Stock wastage {_lakh(stock)}; billing wastage {_lakh(billing)}.",
        "Consumption figures on these rows are those printed on the wastage extract, used for wastage %. "
        "Official store consumption for 1 Apr–8 Sep is in the consumption lookup.",
        "city | store | total wastage | stock | billing | items",
    ]
    ranked = sorted(stores, key=lambda r: _num(r.get("total_wastage_amt")) or 0, reverse=True)
    for row in ranked[:12]:
        lines.append(
            f"{row.get('city')} | {row.get('store')} | {_lakh(_num(row.get('total_wastage_amt')))} | "
            f"{_lakh(_num(row.get('stock_wastage_amt')))} | {_lakh(_num(row.get('billing_wastage_amt')))} | "
            f"{row.get('item_count')}"
        )
    if items:
        lines.append("city | store | item | total wastage qty | amt | %")
        top = sorted(items, key=lambda r: _num(r.get("total_wastage_amt")) or 0, reverse=True)
        for row in top[:8]:
            pct = row.get("wastage_pct") or "blank"
            lines.append(
                f"{row.get('city')} | {row.get('store')} | {row.get('item')} | "
                f"{row.get('total_wastage_qty') or ''} {row.get('unit') or ''} | "
                f"{_lakh(_num(row.get('total_wastage_amt')))} | {pct}"
            )
    lines.append("A store or item that is not in the extract is left out, not treated as zero.")
    return "\n".join(lines)


def _consumption_store_key(label):
    from app.procurement.food_cost import store_key
    return store_key(label)


def _pct_one(part, whole):
    if part is None or whole is None or whole == 0:
        return None
    value = (Decimal(str(part)) / Decimal(str(whole)) * Decimal(100)).quantize(Decimal("0.1"))
    return f"{value}%"


def _store_in_question(folded, rows):
    """The store named in the question, if exactly one matches."""
    hits = []
    for row in rows:
        name = (row.get("store") or "")
        key = _consumption_store_key(name)
        folded_name = name.casefold()
        if key and key in folded:
            hits.append((len(key), name, row))
        elif folded_name and folded_name in folded:
            hits.append((len(folded_name), name, row))
    if not hits:
        return None
    longest = max(h[0] for h in hits)
    best = [h for h in hits if h[0] == longest]
    names = {h[1] for h in best}
    if len(names) == 1:
        return best[0][2]
    return None


def _consumption_gap_text(folded, year, month, label):
    """Known missing store-months: 'not available', no figure."""
    who, how, _ = _OWNERS["consumption"]
    tail = f"That would come from {who}, {how}. No figure is given."
    tokens = folded.replace("(", " ").replace(")", " ").replace("-", " ").split()
    if "02/0017" in folded or "02-0017" in folded or (
        "fra" in tokens and "faridabad" not in folded
    ) or "north fra" in folded:
        return (
            f"North FRA (02/0017) {label} consumption is not available. "
            "No file for that deployment was in the drop for any period. " + tail
        )
    if "chattarpur" in folded:
        return (
            f"Chattarpur is out of the consumption base (closed). "
            f"The {label} file (and the other months in the drop) was a zero-value item catalogue, "
            "same size as the other Chattarpur files, and was excluded. No figure is given."
        )
    if "gk1" in folded or "gk 1" in folded:
        return (
            f"GK1 Cloud Kitchen is out of the consumption base (closed). "
            f"The {label} file (and the other months in the drop) had leftover opening quantities "
            "with zero amounts and zero consumption, identical across months, and was excluded. "
            "No figure is given."
        )
    if "event" in folded or "catering" in folded:
        return (
            f"Events & Catering {label} consumption is not available. "
            "No consumption file for that deployment was in the drop. No figure is given."
        )
    if (year, month) == (2026, 4) and any(
        t in folded for t in ("sec 31", "sector 31", "sec31", "gurgaon 31")
    ):
        return (
            f"Sec 31 Gurgaon April 2026 consumption is not available. "
            "The April file was not in the drop (May–8 Sep are present). No figure is given."
        )
    return None


def _answer_consumption(year, month, question, role):
    if not month_loaded("consumption", year, month, role):
        return missing_text("consumption", year, month)
    stores = _filter_month(_read_csv("consumption_store_month.csv"), year, month)
    items = _filter_month(_read_csv("consumption_item_month.csv"), year, month)
    if not stores:
        return missing_text("consumption", year, month)
    folded = (question or "").casefold()
    label = _label(year, month)
    gap = _consumption_gap_text(folded, year, month, label)
    if gap:
        return gap

    city = _city_from_question(folded)
    picked_store = _store_in_question(folded, stores)
    if picked_store:
        city = ""
        rows = [picked_store]
    else:
        rows = [r for r in stores if not city or r.get("city") == city]
        if city and not rows:
            return (
                f"{city} {label} consumption is not available. No figure is given. "
                "That would come from Procurement, who pulls the PurchaseEasy consumption reports."
            )

    first = min(r.get("first_day") or "9999" for r in rows)
    last = max(r.get("last_day") or "" for r in rows)
    complete = all(r.get("complete") == "yes" for r in rows)
    span = f"{first} to {last}"
    completeness = "complete calendar month" if complete else "incomplete, not a full calendar month"
    sales = _filter_month(_read_csv("sales_store_month.csv"), year, month)
    sales_by_key = {}
    for row in sales:
        sales_by_key[_consumption_store_key(row.get("store"))] = row

    def food_cost_line(row):
        raw = _dec(row.get("consumption_amt_raw")) or Decimal(0)
        semi = _dec(row.get("consumption_amt_semi")) or Decimal(0)
        food = _dec(row.get("consumption_amt_food")) or (raw + semi)
        pack = _dec(row.get("consumption_amt_packaging")) or Decimal(0)
        matched = sales_by_key.get(_consumption_store_key(row.get("store")))
        gross = _dec(matched.get("gross")) if matched else None
        pct = _pct_one(food, gross) if complete and gross else None
        pack_pct = _pct_one(pack, gross) if complete and gross else None
        bits = [
            f"raw {_lakh(raw)}",
            f"semi-processed {_lakh(semi)}",
            f"food (raw + semi) {_lakh(food)}",
            f"packaging {_lakh(pack)} (shown separately, not in food cost)",
        ]
        if gross is None:
            bits.append("Posist gross is not available for this store-month, so the food-cost percent is not stated.")
        elif not complete:
            bits.append(
                f"Posist gross {_lakh(gross)}. A food-cost percent is not stated because "
                f"consumption covers {span}, which is {completeness}, and the sales window may not match."
            )
        else:
            bits.append(f"Posist gross {_lakh(gross)}. Food cost {pct}.")
            if pack_pct:
                bits.append(f"Packaging is {pack_pct} of gross.")
        return " ".join(bits), food, pack, gross, pct

    lines = [
        f"{label} consumption, from PurchaseEasy Consumption Reports, {span} ({completeness}). "
        "Food cost is (raw + semi-processed consumption) / Posist gross. "
        "Raw means the Food and Beverage super-categories. Packaging is shown separately. "
        "Chattarpur and GK1 Cloud Kitchen are excluded. "
        "North FRA (02/0017) has no data. Missing store-months are 'not available', with no figure.",
    ]

    item_hits = []
    scored = []
    for it in items:
        name = (it.get("item") or "").casefold()
        if len(name) >= 4 and name in folded:
            if picked_store and it.get("store") != picked_store.get("store"):
                continue
            if city and it.get("city") != city:
                continue
            scored.append((len(name), it))
    if scored:
        longest = max(s[0] for s in scored)
        item_hits = [s[1] for s in scored if s[0] == longest]

    if picked_store:
        row = picked_store
        detail, food, pack, gross, pct = food_cost_line(row)
        lines.append(f"{row.get('store')} ({row.get('city')}): {detail}")
    elif not city:
        raw = sum((_dec(r.get("consumption_amt_raw")) or 0) for r in rows)
        semi = sum((_dec(r.get("consumption_amt_semi")) or 0) for r in rows)
        food = sum((_dec(r.get("consumption_amt_food")) or 0) for r in rows)
        pack = sum((_dec(r.get("consumption_amt_packaging")) or 0) for r in rows)
        matched_food = Decimal(0)
        matched_gross = Decimal(0)
        matched_n = 0
        for r in rows:
            s = sales_by_key.get(_consumption_store_key(r.get("store")))
            if s and _dec(s.get("gross")):
                matched_food += _dec(r.get("consumption_amt_food")) or 0
                matched_gross += _dec(s.get("gross"))
                matched_n += 1
        lines.append(
            f"Across {len(rows)} loaded stores: raw {_lakh(raw)}, semi-processed {_lakh(semi)}, "
            f"food (raw + semi) {_lakh(food)}, packaging {_lakh(pack)} (shown separately)."
        )
        if complete and matched_n and matched_gross:
            lines.append(
                f"Food cost {_pct_one(matched_food, matched_gross)} "
                f"across the {matched_n} stores that have both consumption and Posist gross "
                f"(gross {_lakh(matched_gross)}). Events & Catering consumption is not available."
            )
        elif not complete:
            lines.append(
                "A food-cost percent is not stated for this window because it is not a full calendar month."
            )
        for city_name in ("Kolkata", "NCR"):
            sub = [r for r in rows if r.get("city") == city_name]
            if not sub:
                continue
            c_food = sum((_dec(r.get("consumption_amt_food")) or 0) for r in sub)
            c_pack = sum((_dec(r.get("consumption_amt_packaging")) or 0) for r in sub)
            c_gross = Decimal(0)
            c_food_m = Decimal(0)
            c_n = 0
            for r in sub:
                s = sales_by_key.get(_consumption_store_key(r.get("store")))
                if s and _dec(s.get("gross")):
                    c_gross += _dec(s.get("gross"))
                    c_food_m += _dec(r.get("consumption_amt_food")) or 0
                    c_n += 1
            extra = ""
            if complete and c_n and c_gross:
                extra = f" Food cost {_pct_one(c_food_m, c_gross)} on {c_n} stores (gross {_lakh(c_gross)})."
            lines.append(
                f"{city_name}: food (raw + semi) {_lakh(c_food)}, packaging {_lakh(c_pack)}, "
                f"{len(sub)} stores.{extra}"
            )
    else:
        raw = sum((_dec(r.get("consumption_amt_raw")) or 0) for r in rows)
        semi = sum((_dec(r.get("consumption_amt_semi")) or 0) for r in rows)
        food = sum((_dec(r.get("consumption_amt_food")) or 0) for r in rows)
        pack = sum((_dec(r.get("consumption_amt_packaging")) or 0) for r in rows)
        matched_food = Decimal(0)
        matched_gross = Decimal(0)
        matched_n = 0
        for r in rows:
            s = sales_by_key.get(_consumption_store_key(r.get("store")))
            if s and _dec(s.get("gross")):
                matched_food += _dec(r.get("consumption_amt_food")) or 0
                matched_gross += _dec(s.get("gross"))
                matched_n += 1
        lines.append(
            f"{city}: raw {_lakh(raw)}, semi-processed {_lakh(semi)}, "
            f"food (raw + semi) {_lakh(food)}, packaging {_lakh(pack)} (shown separately), "
            f"{len(rows)} stores."
        )
        if complete and matched_n and matched_gross:
            lines.append(
                f"Food cost {_pct_one(matched_food, matched_gross)} "
                f"across the {matched_n} stores with both consumption and Posist gross "
                f"(gross {_lakh(matched_gross)})."
            )
        elif not complete:
            lines.append(
                "A food-cost percent is not stated for this window because it is not a full calendar month."
            )

    show = sorted(rows, key=lambda r: _num(r.get("consumption_amt_food")) or 0, reverse=True)
    lines.append("store | city | raw | semi | food (raw+semi) | packaging | food cost")
    for row in show[:16]:
        _, food, pack, gross, pct = food_cost_line(row)
        pct_txt = pct or "not stated"
        lines.append(
            f"{row.get('store')} | {row.get('city')} | "
            f"{_lakh(_num(row.get('consumption_amt_raw')))} | "
            f"{_lakh(_num(row.get('consumption_amt_semi')))} | "
            f"{_lakh(_num(row.get('consumption_amt_food')))} | "
            f"{_lakh(_num(row.get('consumption_amt_packaging')))} | {pct_txt}"
        )

    if item_hits:
        lines.append("item | store | category | consumption qty | consumption amt | bucket")
        for it in item_hits[:12]:
            qty = it.get("consumption_qty") or ""
            unit = it.get("unit") or ""
            lines.append(
                f"{it.get('item')} | {it.get('store')} | {it.get('category')} | "
                f"{qty} {unit} | {_lakh(_num(it.get('consumption_amt')))} | {it.get('bucket')}"
            )
    if "recipe" in folded:
        lines.append(
            "A consumption-versus-recipe comparison is not computed for these monthly extracts. "
            "The figures above are what the Consumption Report shows. No recipe cost is invented."
        )

    if (year, month) == (2026, 4):
        lines.append("Sec 31 Gurgaon has no April consumption file; that store-month is not available.")
    if month == 9 and year == 2026:
        lines.append(
            "September consumption is 1–8 Sep only, while Posist sales cover the full month, "
            "so a full-month food-cost percent is not stated."
        )
    lines.append("A store-month that is not in the drop is not available, not treated as zero.")
    return "\n".join(lines)



_ANSWERS = {
    "sales": _answer_sales,
    "channel": _answer_channel,
    "procurement": _answer_procurement,
    "menu_mix": _answer_menu,
    "reelo": _answer_reelo,
    "aggregator": _answer_aggregator,
    "finance": _answer_finance,
    "tally": _answer_tally,
    "hr": _answer_hr,
    "famepilot": _answer_famepilot,
    "wastage": _answer_wastage,
    "consumption": _answer_consumption,
}


def lookup(question, role="ops", month=None, domain=None):
    """Figures for one calendar month and one domain. Missing months are named, never estimated."""
    folded = (question or "").casefold()
    if domain is None:
        domain = _detect_domain(folded)
    if month is None:
        month, year = _month_named(folded)
    else:
        if isinstance(month, str) and re.fullmatch(r"20\d{2}-\d{2}", month):
            year, month = int(month[:4]), int(month[5:7])
        else:
            month = int(month)
            year_match = re.search(r"\b(20\d{2})\b", folded)
            year = int(year_match.group(1)) if year_match else 2026
    if domain is None and month is None:
        return (
            "Name a month and a domain (sales, channel, procurement, wastage, consumption, menu mix, Reelo, "
            "aggregator, finance, Tally, HR, or Famepilot). No figure is assumed."
        )
    if month is None:
        return "Name the month. No monthly total was assumed."
    if year < 2026 or (year == 2026 and month < 4) or (year == 2026 and month > 11) or year > 2026:
        # Still answer if they ask March 2026 or Dec: say outside the window / not loaded
        if domain:
            return missing_text(domain, year, month)
        return (
            f"{_label(year, month)} is outside the loaded history window "
            f"(1 Apr 2026 to {_short(_WINDOW_END.isoformat())}). No figure is invented."
        )
    if domain is None:
        # Tell them what is and isn't loaded that month, without inventing figures
        key = f"{year:04d}-{month:02d}"
        loaded = []
        missing = []
        for record in _domains(role):
            if key in (record.get("months_loaded") or []):
                loaded.append(f"{record.get('label')} ({record.get('owner')})")
            elif key in (record.get("months_missing") or []):
                missing.append(f"{record.get('label')} would come from {record.get('owner')}")
        lines = [f"{_label(year, month)}: name the domain for figures."]
        if loaded:
            lines.append("Loaded: " + "; ".join(loaded) + ".")
        if missing:
            lines.append("Not loaded: " + "; ".join(missing) + ". No figure is invented.")
        return " ".join(lines)
    # "Swiggy vs Zomato" is aggregator when Sanjoy's workbook is loaded, and
    # Posist channel when only the channel extract is loaded for that month.
    if (
        domain == "aggregator"
        and not month_loaded("aggregator", year, month, role)
        and month_loaded("channel", year, month, role)
        and "sanjoy" not in folded
        and "aggregator" not in folded
        and "ad spend" not in folded
        and "impression" not in folded
        and "refund" not in folded
    ):
        domain = "channel"
    if not _allowed(domain, role):
        return _role_denied(domain)
    handler = _ANSWERS.get(domain)
    if handler is None:
        return missing_text(domain, year, month)
    return handler(year, month, question, role)


def relevant(question, role="ops"):
    folded = (question or "").casefold()
    month, year = _month_named(folded)
    domain = _detect_domain(folded)
    if month is None:
        return False
    if domain == "aggregator":
        return True
    if domain and domain != "sales":
        return True
    if domain == "sales":
        # Loaded sales months stay with month_sales (detailed store tables).
        return not month_loaded("sales", year, month, role)
    return True  # a month with no domain: coverage pointer


def use_file_answer(question, role="ops"):
    """True when the file-backed history answer must not be rewritten."""
    folded = (question or "").casefold()
    month, year = _month_named(folded)
    domain = _detect_domain(folded)
    if month is None or domain is None:
        return False
    if domain == "sales" and month_loaded("sales", year, month, role):
        return False
    if domain == "sales" and any(token in folded for token in _SKIP_SALES):
        # aggregator etc. already classified away from sales
        return False
    return True


def packet(question, role="ops"):
    """Optional extra block for the prompt, only when the question names a month."""
    if not relevant(question, role):
        return ""
    text = lookup(question, role)
    if not text:
        return ""
    return "History lookup for the asked month:\n" + text


def answer(question, data, owner):
    from app.chat.facts import _pack

    role = (data or {}).get("role") or ("owner" if owner else "ops")
    text = lookup(question, role)
    folded = (question or "").casefold()
    month, year = _month_named(folded)
    as_of = ""
    if month:
        last = monthrange(year, month)[1]
        as_of = f"{last} {_MONTH_SHORT[month]} {year}"
    domain = _detect_domain(folded) or "sales"
    kind = "finance" if domain in {"finance", "tally", "hr"} else (
        "procurement" if domain in {"procurement", "menu_mix", "wastage", "consumption"} else "sales"
    )
    return _pack(text, as_of, kind, question, owner, source={"text": text})


def tool_result(arguments, role):
    question = ""
    month = None
    domain = None
    if isinstance(arguments, dict):
        question = str(arguments.get("question") or "")
        month = arguments.get("month") or None
        domain = arguments.get("domain") or None
        if domain:
            domain = str(domain).strip().casefold().replace(" ", "_")
            aliases = {
                "menu": "menu_mix", "p&l": "finance", "pnl": "finance",
                "tickets": "famepilot", "waste": "wastage",
                "food_cost": "consumption", "foodcost": "consumption", "consume": "consumption",
            }
            domain = aliases.get(domain, domain)
    return {"text": lookup(question, role, month=month, domain=domain)}
