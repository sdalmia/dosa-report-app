"""A report built from loaded figures, as a PDF and as Excel.

One sheet per table. Numbers stay numbers. Every table carries its coverage dates.
Finance, HR, the inbox, and Tally stay off unless this role may see them.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.chat.facts import _as_of

_FONT = Path(__file__).resolve().parents[1] / "store_health" / "fonts" / "DejaVuSans.ttf"
_FONT_BOLD = Path(__file__).resolve().parents[1] / "store_health" / "fonts" / "DejaVuSans-Bold.ttf"


def asks_for_file(question):
    folded = " ".join((question or "").casefold().split())
    return any(token in folded for token in (
        "pdf", "xlsx", "xls", "excel", "spreadsheet", "download a", "make me a",
        "give me an xls", "give me a pdf", "give me an excel", "report of", "a report",
        "give me bills", "bills by store", "bill by store",
    ))


def build_report(question, data, owner, answer, generated_by=""):
    """Sections for one report. Figures come from the loaded view."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.chat.correctness import cover_lines, data_footer
    from app.chat.guard import can_see_books, can_see_pl

    role = (data or {}).get("role") or ("owner" if owner else "ops")
    see_pl = can_see_pl(role, owner)
    see_books = can_see_books(role, owner)
    see_people = role in {"owner", "hr"}
    from app.chat.daily_review import build as build_review, section_id
    if section_id(question):
        built = build_review(Path(__file__).resolve().parents[2], see_pl, see_people)
        tables = []
        kpis = []
        for section in built["sections"]:
            rows = section.get("full_rows") or section["rows"]
            if not rows and not section.get("verdict"):
                continue
            tables.append({
                "name": section["title"],
                "coverage": section["coverage"],
                "columns": section["columns"],
                "rows": rows or [[section["verdict"]]],
            })
            tone = "ink"
            verdict = section.get("verdict") or ""
            head = verdict.split(":", 1)[0].casefold()
            if head.startswith("behind") or head.startswith("de-growing"):
                tone = "red"
            elif head.startswith("ahead") or head.startswith("growing"):
                tone = "green"
            if len(kpis) < 4:
                sentence = verdict.split(". ")[0].strip()
                if len(sentence) > 78:
                    sentence = sentence[:75].rsplit(" ", 1)[0] + "…"
                kpis.append({"label": section["title"].split(". ", 1)[-1], "value": sentence, "tone": tone})
        moment = datetime.now(ZoneInfo("Asia/Kolkata"))
        who = generated_by or ("owner login" if role == "owner" else f"{role} login")
        day = built.get("day")
        coverage = day.strftime("%-d %b %Y") if day else (built.get("note") or "not loaded")
        return {
            "title": "Daily review",
            "coverage": coverage,
            "sales_through": built.get("note") or coverage,
            "data_lines": [built.get("note") or coverage],
            "footer": "",
            "generated_by": who,
            "generated_at": moment.strftime("%d %b %Y, %I:%M %p IST").lstrip("0"),
            "insight": kpis[0]["value"] if kpis else "Daily review",
            "tables": tables,
            "steps": _steps(answer, data, owner and see_pl),
            "chart": None,
            "kpis": kpis,
            "owner_only": bool(see_pl),
        }
    kind = _kind(question)
    coverage = _coverage(data, kind)
    title = _title(question, kind)
    if "real problem" in (question or "").casefold() and "delhi" in (question or "").casefold():
        title = "Delhi"
    tables = []
    if kind in {"finance", "people", "inbox", "tally"} and not _allowed(kind, see_pl, see_people, see_books):
        tables.append(_refusal_table(kind, coverage))
        tables.append(_sales_table(data, _coverage(data, "sales")))
    elif kind == "finance":
        tables.append(_finance_table(data, True, coverage))
    elif kind == "people":
        tables.append(_people_table(data, True, coverage))
    elif kind == "inbox":
        tables.append(_private_table("Inbox", True, coverage, "Inbox"))
    elif kind == "tally":
        tables.append(_private_table("Tally", True, coverage, "Tally"))
    elif kind == "food":
        tables.append(_food_table(data, coverage))
    elif kind == "bills":
        tables.append(_bills_table(data, coverage))
    else:
        tables.append(_sales_table(data, coverage))
    if kind == "sales":
        moves = _moves_table(data, owner)
        if moves:
            tables.append(moves)
    steps = _steps(answer, data, owner and see_pl)
    chart = _chart(data, tables[-1] if kind in {"finance", "people", "inbox", "tally"} and len(tables) > 1 else tables[0])
    moment = datetime.now(ZoneInfo("Asia/Kolkata"))
    who = generated_by or ("owner login" if role == "owner" else f"{role} login")
    return {
        "title": title,
        "coverage": coverage,
        "sales_through": "\n".join(cover_lines(data)) or f"Sales through {coverage}.",
        "data_lines": cover_lines(data),
        "footer": data_footer(data, question),
        "generated_by": who,
        "generated_at": moment.strftime("%d %b %Y, %I:%M %p IST").lstrip("0"),
        "insight": _insight(answer, tables[0]),
        "tables": tables,
        "steps": steps,
        "chart": chart,
        "owner_only": bool(see_pl and kind in {"finance", "people"}),
    }


def render_pdf(report):
    from app.chat.pdf_layout import render_pdf as _render
    return _render(report)


def render_xlsx(report):
    from app.chat.pdf_layout import render_xlsx as _render
    return _render(report)


def _kind(question):
    folded = " ".join((question or "").casefold().split())
    if any(token in folded for token in ("profit", "ebitda", "p&l", "p and l")):
        return "finance"
    if "inbox" in folded or "important email" in folded:
        return "inbox"
    if "tally" in folded:
        return "tally"
    if "bill" in folded:
        return "bills"
    if "food cost" in folded or "food-cost" in folded:
        return "food"
    if any(token in folded for token in ("headcount", "staff lead", " hr ")):
        return "people"
    return "sales"


def _title(question, kind):
    names = {
        "sales": "Store performance",
        "food": "Food cost by store",
        "finance": "Profit",
        "bills": "Bills by store",
        "people": "People",
        "inbox": "Inbox",
        "tally": "Tally",
    }
    return names.get(kind) or "Dosa Coffee"


def _coverage(data, kind):
    windows = (data or {}).get("sales_windows") or {}
    summary = (data or {}).get("summary") or {}
    if kind == "food":
        for row in ((data or {}).get("dossiers") or {}).values():
            period = ((row.get("food") or {}).get("period")) or ""
            if period:
                return period
    if windows.get("week_start") and windows.get("latest"):
        return f"{_as_of(windows.get('week_start'))}–{_as_of(windows.get('latest'))}"
    if summary.get("as_of_date"):
        return _as_of(summary.get("as_of_date"))
    return "not loaded"


def _allowed(kind, see_pl, see_people, see_books):
    if kind == "finance":
        return see_pl
    if kind == "people":
        return see_people
    if kind in {"inbox", "tally"}:
        return see_books
    return True


def _refusal_table(kind, coverage):
    notes = {
        "finance": "Profit, rent, and the full P&L are not on this login. Store sales, food cost percent, and bills are available instead.",
        "people": "People details are not on this login. Store sales are available instead.",
        "inbox": "The inbox is not on this login. Store sales are available instead.",
        "tally": "Tally is not on this login. Store sales are available instead.",
    }
    return {
        "name": "Not on this login",
        "coverage": coverage,
        "columns": ["Note"],
        "rows": [[notes.get(kind, "Not included for this role.")]],
    }


def _bills_table(data, coverage):
    rows = []
    for row in ((data or {}).get("sales_windows") or {}).get("week_rows") or []:
        name = row.get("store") or ""
        if _closed(name):
            continue
        gross = row.get("gross")
        if gross in (None, 0):
            continue
        bills = _bills_cell(row, name)
        rows.append([_short(name), bills, float(gross)])
    rows.sort(key=lambda item: item[2], reverse=True)
    return {
        "name": "Bills by store",
        "coverage": coverage,
        "columns": ["Store", "Bills", "Gross rupees"],
        "numeric": [1, 2],
        "rows": rows or [["No open store is loaded", None, None]],
    }


def _sales_table(data, coverage):
    rows = []
    for row in ((data or {}).get("sales_windows") or {}).get("week_rows") or []:
        name = row.get("store") or ""
        if _closed(name):
            continue
        gross = row.get("gross")
        if gross in (None, 0):
            continue
        bills = _bills_cell(row, name)
        rows.append([_short(name), row.get("region") or "", float(gross), bills])
    rows.sort(key=lambda item: item[2], reverse=True)
    return {
        "name": "Store performance",
        "coverage": coverage,
        "columns": ["Store", "City", "Gross (Rs)", "Bills"],
        "numeric": [2, 3],
        "rows": rows or [["No open store is loaded", "", None, None]],
    }


def _food_table(data, coverage):
    rows = []
    period = coverage
    for row in ((data or {}).get("dossiers") or {}).values():
        food = row.get("food") or {}
        if food.get("sanity") or food.get("pct") is None:
            continue
        if _closed(row.get("name") or ""):
            continue
        period = food.get("period") or period
        packaging = _percent_number(food.get("packaging_pct"))
        rows.append([_short(row.get("name") or ""), round(float(food["pct"]), 2), packaging])
    rows.sort(key=lambda item: item[1], reverse=True)
    return {
        "name": "Food cost",
        "coverage": period or coverage,
        "columns": ["Store", "Food cost percent", "Packaging percent"],
        "numeric": [1, 2],
        "rows": rows or [["No food-cost row is loaded", None, None]],
    }


def _finance_table(data, allowed, coverage):
    if not allowed:
        return {
            "name": "Profit",
            "coverage": coverage,
            "columns": ["Note"],
            "rows": [["Not included for this role."]],
        }
    rows = []
    for card in (data or {}).get("finance") or []:
        rows.append([card.get("kicker") or "", card.get("label") or "", card.get("value") or ""])
    if not rows:
        rows = [["Profit is not loaded", "", ""]]
    return {
        "name": "Profit",
        "coverage": coverage,
        "columns": ["Period", "Line", "Figure"],
        "rows": rows,
    }


def _people_table(data, allowed, coverage):
    if not allowed:
        return {
            "name": "People",
            "coverage": coverage,
            "columns": ["Note"],
            "rows": [["Not included for this role."]],
        }
    rows = []
    for row in ((data or {}).get("dossiers") or {}).values():
        hr = row.get("hr") or {}
        if hr.get("lead") or hr.get("headcount"):
            rows.append([_short(row.get("name") or ""), hr.get("lead") or "", hr.get("headcount") or ""])
    return {
        "name": "People",
        "coverage": coverage,
        "columns": ["Store", "Lead", "Headcount"],
        "rows": rows or [["No people row is loaded", "", ""]],
    }


def _private_table(name, allowed, coverage, label):
    if not allowed:
        note = "Not included for this role."
    else:
        note = f"{label} is only on the owner login, and no rows were copied into this file."
    return {
        "name": name,
        "coverage": coverage,
        "columns": ["Note"],
        "rows": [[note]],
    }


def _moves_table(data, owner):
    from app.chat.guard import can_see_pl
    from app.chat.sizing import move_lines

    role = (data or {}).get("role") or ("owner" if owner else "ops")
    lines = move_lines(can_see_pl(role, owner))
    if not lines:
        return None
    rows = []
    for line in lines:
        value = ""
        how = ""
        if "Value:" in line and "How sized:" in line:
            value = line.split("Value:", 1)[1].split("How sized:", 1)[0].strip()
            how = line.split("How sized:", 1)[1].split("Owner:", 1)[0].strip()
        rows.append([line.split(". ", 1)[0][:80], value, how])
    return {
        "name": "Moves",
        "coverage": "17-23 Nov 2026 against 20 Oct-2 Nov 2026",
        "columns": ["Move", "Value", "How sized"],
        "rows": rows,
    }


def _steps(answer, data, owner):
    lines = []
    for line in (answer or "").splitlines():
        text = line.strip()
        if text[:2] in {"1.", "2.", "3.", "4.", "5."} and "Owner:" in text:
            lines.append(text)
    if lines:
        return lines[:5]
    try:
        from app.chat.facts import actions_from_data
        actions = actions_from_data(data or {}, owner)
    except Exception:
        actions = []
    if not actions:
        return ["No next step is backed by a loaded figure."]
    return [f"{action.get('what')} {action.get('why')}".strip() for action in actions[:5]]


def _insight(answer, table):
    text = (answer or "").replace("**", " ").replace("Mock answer.", "").strip()
    first = text.split("\n", 1)[0].strip()
    if first and "ready with this answer" not in first and len(first) < 400:
        return first
    rows = table.get("rows") or []
    if rows and rows[0] and rows[0][0] not in {"No open store is loaded", "Not included for this role."}:
        return f"The lead row is {rows[0][0]}."
    return "The loaded rows are below."


def _chart(data, table):
    series = []
    columns = table.get("columns") or []
    numeric_at = None
    for label in ("Gross (Rs)", "Gross rupees"):
        if label in columns:
            numeric_at = columns.index(label)
            break
    if numeric_at is None and "Food cost percent" in (table.get("columns") or []):
        numeric_at = 1
    if numeric_at is None:
        return None
    for row in (table.get("rows") or [])[:5]:
        if len(row) <= numeric_at or not isinstance(row[numeric_at], (int, float)):
            continue
        from app.chat.names import clip_label
        series.append({"label": clip_label(row[0]), "value": float(row[numeric_at])})
    if not series:
        return None
    return {"title": table.get("name") or "Chart", "series": series}


def _percent_number(value):
    if value is None or value == "":
        return None
    text = str(value).replace("%", "").strip()
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _closed(name):
    text = (name or "").casefold()
    return "faridabad" in text or "chattarpur" in text or "gk1" in text or "gk 1" in text


def _mall(name):
    text = (name or "").casefold()
    return "manisquare" in text or "forum" in text


def _bills_cell(row, name):
    if row.get("mall_bulk") or _mall(name):
        return "excluded (mall bulk bills)"
    bills = row.get("bills")
    if bills in (None, ""):
        return None
    return int(round(float(bills)))


def _short(name):
    from app.chat.names import clean_store_name
    return clean_store_name(name)


def _pdf_cell(column, value):
    from app.chat.names import bill_count, rs_rupees
    if value is None:
        return ""
    header = (column or "").casefold()
    if isinstance(value, str):
        return value
    if "bill" in header and isinstance(value, (int, float)):
        return bill_count(value)
    if "gross" in header and isinstance(value, (int, float)):
        return rs_rupees(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _pdf_line(pdf, text, size, bold=False):
    if text is None:
        return
    pdf.set_x(pdf.l_margin)
    pdf.set_font("DejaVu", "B" if bold else "", size)
    pdf.multi_cell(0, 6, str(text))


def _bars(pdf, series):
    peak = max(abs(float(item.get("value") or 0)) for item in series) or 1
    for item in series[:5]:
        value = float(item.get("value") or 0)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("DejaVu", "", 9)
        from app.chat.names import clip_label
        pdf.cell(70, 6, clip_label(item.get("label") or "", 36))
        width = max(2, abs(value) / peak * 80)
        y = pdf.get_y() + 1
        pdf.set_fill_color(122, 78, 13)
        pdf.rect(pdf.get_x(), y, width, 4, style="F")
        pdf.ln(6)


def _sheet_name(name):
    cleaned = "".join(ch for ch in (name or "Sheet") if ch not in "[]:*?/\\")
    return (cleaned or "Sheet")[:31]
