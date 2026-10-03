"""A4 store-health PDF. Figures come from the same view as the page."""

import logging
from datetime import datetime
from pathlib import Path

logging.getLogger("fontTools").setLevel(logging.ERROR)
logging.getLogger("fpdf").setLevel(logging.ERROR)

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.store_health.present import IST, format_ist


_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_LABELS = {
    "net": "Net",
    "gross": "Gross",
    "bills": "Bills",
    "apb": "APB",
    "net_wow_pct": "Net week over week",
    "bills_wow_pct": "Bills week over week",
    "apb_wow_pct": "APB week over week",
    "net_last_same_weekday": "Net, last same weekday",
    "bills_last_same_weekday": "Bills, last same weekday",
    "apb_last_same_weekday": "APB, last same weekday",
    "unsettled_bills": "Unsettled bills",
    "unsettled_amount": "Unsettled amount",
    "void_bills": "Void bills",
    "keka_location": "Keka location",
    "headcount": "Registered employees",
    "primary_lead": "Primary lead",
    "other_leads": "Other leads",
    "match_status": "Match status",
    "keka_note": "Note",
    "audit_avg": "Average",
    "audit_weekday": "Weekday",
    "audit_weekend": "Weekend",
    "audit_status": "Status",
    "audit_note": "Note",
    "audit_period": "Period",
    "brand_avg": "Brand average",
    "brand_weekday": "Brand weekday",
    "brand_weekend": "Brand weekend",
    "brand_status": "Brand status",
    "brand_note": "Brand note",
    "brand_period": "Brand period",
    "rating": "Public rating",
    "review_count": "Public reviews",
    "private_rating": "Private rating",
    "private_review_count": "Private reviews",
    "overall_reviews": "Overall reviews",
    "main_threat": "Main threat",
    "famepilot_location": "Famepilot location",
    "famepilot_note": "Match note",
    "redemption_rate": "Redemption rate",
    "times_redeemed": "Times redeemed",
    "redemption_revenue": "Redemption revenue",
    "avg_redemption_revenue": "Average per redemption",
    "phone_capture": "Phone capture",
    "phones_valid": "Valid visits",
    "phones_blocked": "Blocked visits",
    "visits": "Visits",
    "active_customers": "Active customers",
    "points_issued": "Points issued",
    "sales_total": "Sales, last 30 days",
    "customers_with_purchase": "Customers with a purchase",
    "inactive_customers": "Inactive customers",
    "reelo_store": "Reelo store",
    "reelo_date_range": "Date range in the file",
    "reelo_match_status": "Match status",
    "reelo_note": "Note",
    "weekday": "Weekday",
    "tier": "Tier",
    "pred_low": "Pred low",
    "pred_high": "Pred high",
    "pred_mid": "Pred mid",
    "actual_net": "Actual Net",
    "variance_vs_mid": "Variance vs mid",
    "variance_pct": "Variance %",
    "status": "Status",
    "drivers": "Drivers",
    "notes": "Notes",
}


class _StorePdf(FPDF):
    def __init__(self, store_label):
        super().__init__(format="A4", unit="mm")
        self.store_label = store_label
        self.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(14, 14, 14)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_text_color(60, 60, 60)
        self.set_font("DejaVu", "", 8)
        self.cell(0, 6, self.store_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def footer(self):
        self.set_y(-12)
        self.set_text_color(60, 60, 60)
        self.set_font("DejaVu", "", 8)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def render_store_pdf(store, selection, view, insights, context_slots, warnings=None):
    pdf = _StorePdf(store.label)
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    _text(pdf, "Store Health", 18, bold=True)
    _text(pdf, store.label, 14, bold=True)
    if store.region:
        _text(pdf, f"Region: {store.region}", 11)
    start = selection.get("start_input") or ""
    end = selection.get("end_input") or ""
    day = selection.get("day_input") or ""
    _text(pdf, f"Date range: {start} to {end}. Selected day: {day}.", 11)
    _text(pdf, f"Prepared {format_ist(datetime.now(IST))}. Blank cells are not zero.", 9)
    pdf.ln(1)

    _section(pdf, "Last updated")
    for line in _freshness_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "1. Posist Insights")
    for line in _posist_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "2. Mystery Audit")
    for line in _audit_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "3. Staff strength")
    for line in _keka_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "4. Famepilot")
    for line in _fame_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "5. Reelo")
    for line in _reelo_lines(view):
        _text(pdf, line, 10)

    _section(pdf, "6. Actionable insights")
    if insights.get("has_insight"):
        for title, key in (("Ops", "ops"), ("CRM", "crm"), ("Cost", "cost")):
            _text(pdf, title, 12, bold=True)
            for line in insights.get(key) or []:
                _text(pdf, line, 10)
    else:
        _text(pdf, "No ops, CRM, or cost insights are on file for this store.", 10)
    for title, key in (
        ("Holiday calendar", "holiday"),
        ("Local current affairs", "news"),
        ("Weather", "weather"),
    ):
        _text(pdf, title, 12, bold=True)
        for line in _context_lines(context_slots.get(key) or {}):
            _text(pdf, line, 10)

    _section(pdf, "7. Sales calendar")
    for line in _calendar_lines(selection, view):
        _text(pdf, line, 10)

    if warnings:
        _section(pdf, "File warnings")
        for warning in warnings:
            _text(pdf, warning, 9)

    output = pdf.output()
    return bytes(output)


def _section(pdf, title):
    pdf.ln(2)
    _text(pdf, title, 13, bold=True)
    y = pdf.get_y()
    pdf.set_draw_color(180, 180, 180)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(2)


def _text(pdf, text, size, bold=False):
    if not text:
        return
    pdf.set_font("DejaVu", "B" if bold else "", size)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, max(5, size * 0.5), text or "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(0.6)


def _pair(fields, key):
    value = (fields or {}).get(key) or ""
    if not str(value).strip():
        return None
    return f"{_LABELS.get(key, key)}: {value}"


def _pairs(fields, keys):
    lines = []
    for key in keys:
        line = _pair(fields, key)
        if line:
            lines.append(line)
    return lines


def _freshness_lines(view):
    freshness = view.get("freshness") or {}
    lines = []
    for key, title in (
        ("posist", "Posist daily"),
        ("calendar", "Predicted vs actual"),
        ("reelo", "Reelo"),
        ("famepilot", "Famepilot"),
    ):
        slot = freshness.get(key) or {}
        if slot.get("state") in {"ready", "saved"}:
            saved = slot.get("saved_at") or ""
            newest = slot.get("newest_date") or ""
            line = f"{title}: file last saved {saved}."
            if newest:
                line += f" Newest date in the file {newest}."
            lines.append(line)
        else:
            lines.append(f"{title}: {slot.get('detail') or 'Empty.'}")
    reelo = view.get("reelo") or {}
    fame = view.get("fame") or {}
    if reelo.get("window"):
        lines.append(f"Reelo window: {reelo['window']}")
    if fame.get("window") and (view.get("freshness") or {}).get("famepilot", {}).get("state") == "saved":
        lines.append(f"Famepilot window: {fame['window']}")
    return lines


def _posist_lines(view):
    posist = view.get("posist") or {}
    freshness = (view.get("freshness") or {}).get("posist") or {}
    lines = []
    if freshness.get("state") != "ready" and freshness.get("detail"):
        lines.append(freshness["detail"])
    if posist.get("not_on_report"):
        lines.append("Not on the Posist deployment report.")
        return lines
    if posist.get("window_label"):
        lines.append(f"Last window: {posist['window_label']}.")
    if posist.get("days_summed"):
        lines.append(f"Days summed: {posist['days_summed']}.")
    if posist.get("missing_label"):
        lines.append(posist["missing_label"])
    filled = _pairs(
        posist.get("fields") or {},
        [
            "net",
            "gross",
            "bills",
            "apb",
            "net_last_same_weekday",
            "bills_last_same_weekday",
            "apb_last_same_weekday",
            "net_wow_pct",
            "bills_wow_pct",
            "apb_wow_pct",
            "unsettled_amount",
            "unsettled_bills",
            "void_bills",
        ],
    )
    if filled:
        lines.extend(filled)
    elif posist.get("has_row"):
        lines.append("This store is on the Posist report, and the summed cells are blank. A blank is not zero.")
    return lines or ["Posist has no figures for this store."]


def _audit_lines(view):
    audit = view.get("audit") or {}
    lines = []
    state = audit.get("state")
    if state == "missing":
        lines.append("mystery_audit.csv is missing.")
    elif state == "empty":
        lines.append("mystery_audit.csv is empty.")
    if not audit.get("has_row"):
        lines.append("No mystery audit is on file for this store.")
    else:
        lines.extend(
            _pairs(
                audit.get("fields") or {},
                ["audit_period", "audit_avg", "audit_weekday", "audit_weekend", "audit_status", "audit_note"],
            )
        )
    if audit.get("has_brand"):
        lines.append("Brand aggregate (not this store's score).")
        lines.extend(
            _pairs(
                audit.get("fields") or {},
                ["brand_period", "brand_avg", "brand_weekday", "brand_weekend", "brand_status", "brand_note"],
            )
        )
    return lines


def _keka_lines(view):
    keka = view.get("keka") or {}
    lines = []
    if keka.get("caveat"):
        lines.append(keka["caveat"])
    state = keka.get("state")
    if state == "missing":
        lines.append("keka.csv is missing.")
    elif state == "empty":
        lines.append("keka.csv is empty.")
    if not keka.get("has_row"):
        lines.append("No Keka row matches this store.")
    elif keka.get("no_match"):
        lines.append("No Keka match. No manager is on file.")
    else:
        lines.extend(
            _pairs(
                keka.get("fields") or {},
                ["primary_lead", "headcount", "keka_location", "other_leads", "match_status", "keka_note"],
            )
        )
    return lines


def _fame_lines(view):
    fame = view.get("fame") or {}
    freshness = (view.get("freshness") or {}).get("famepilot") or {}
    lines = []
    if fame.get("state") == "saved" and fame.get("window"):
        lines.append(fame["window"])
    elif freshness.get("detail"):
        lines.append(freshness["detail"])
    state = fame.get("state")
    if state == "missing":
        lines.append("famepilot.csv is missing.")
    elif state == "empty":
        lines.append("famepilot.csv is empty.")
    if not fame.get("has_row"):
        lines.append("No Famepilot row matches this store.")
    elif fame.get("no_location"):
        lines.append("No Famepilot location.")
    else:
        lines.extend(
            _pairs(
                fame.get("fields") or {},
                [
                    "rating",
                    "review_count",
                    "private_rating",
                    "private_review_count",
                    "overall_reviews",
                    "main_threat",
                    "famepilot_location",
                    "famepilot_note",
                ],
            )
        )
    return lines


def _reelo_lines(view):
    reelo = view.get("reelo") or {}
    freshness = (view.get("freshness") or {}).get("reelo") or {}
    lines = []
    if reelo.get("phone_caveat"):
        lines.append(reelo["phone_caveat"])
    if reelo.get("state") == "saved" and reelo.get("window"):
        lines.append(reelo["window"])
    elif freshness.get("detail"):
        lines.append(freshness["detail"])
    state = reelo.get("state")
    if state == "missing":
        lines.append("reelo.csv is missing.")
    elif state == "empty":
        lines.append("reelo.csv is empty.")
    if not reelo.get("has_row"):
        lines.append("No Reelo row matches this store.")
    elif reelo.get("not_in_reelo"):
        lines.append("not in Reelo")
    else:
        lines.extend(
            _pairs(
                reelo.get("fields") or {},
                [
                    "redemption_rate",
                    "times_redeemed",
                    "redemption_revenue",
                    "avg_redemption_revenue",
                    "phone_capture",
                    "phones_valid",
                    "phones_blocked",
                    "visits",
                    "active_customers",
                    "points_issued",
                    "sales_total",
                    "customers_with_purchase",
                    "inactive_customers",
                    "reelo_store",
                    "reelo_date_range",
                    "reelo_match_status",
                    "reelo_note",
                ],
            )
        )
    return lines


def _context_lines(slot):
    if not slot or not slot.get("connected"):
        return [slot.get("message") or ""]
    lines = []
    if slot.get("place"):
        lines.append(f"Place: {slot['place']}.")
    if slot.get("source"):
        source = f"Source: {slot['source']}"
        if slot.get("fetched_at"):
            source += f" Fetched {slot['fetched_at']}."
        lines.append(source)
    if slot.get("summary"):
        lines.append(slot["summary"])
    for item in slot.get("entries") or []:
        if item.get("line"):
            lines.append(item["line"])
        elif item.get("date") and item.get("name"):
            lines.append(f"{item['date']}: {item['name']}")
    for day in slot.get("days") or []:
        if day.get("line"):
            lines.append(day["line"])
    if slot.get("message"):
        lines.append(slot["message"])
    return lines or [""]


def _calendar_lines(selection, view):
    if selection.get("error"):
        return [selection["error"]]
    days = view.get("days") or []
    if not days:
        return ["Choose a store to see predicted and actual Net."]
    lines = [
        (
            f"Actual Net is filled on {view.get('filled_actual_days')} of {view.get('day_count')} days. "
            f"A prediction is filled on {view.get('filled_prediction_days')} of {view.get('day_count')} days. "
            "A blank cell is not zero."
        )
    ]
    filled = []
    for day in days:
        fields = day.get("fields") or {}
        if not any(str(value).strip() for value in fields.values()):
            continue
        bits = [day.get("label") or day.get("iso") or ""]
        for key in (
            "weekday",
            "tier",
            "pred_low",
            "pred_high",
            "pred_mid",
            "actual_net",
            "variance_vs_mid",
            "variance_pct",
            "status",
            "drivers",
            "notes",
        ):
            value = fields.get(key) or ""
            if str(value).strip():
                bits.append(f"{_LABELS[key]}: {value}")
        filled.append(" | ".join(bits))
    if not filled:
        lines.append("No predicted or actual Net in this range.")
    else:
        lines.extend(filled)
        blank = (view.get("day_count") or 0) - len(filled)
        if blank:
            lines.append(f"{blank} days in this range have no calendar figures. Those cells are blank, not zero.")
    return lines
