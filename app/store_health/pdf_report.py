"""A4 handout for one store. Figures come from the same view as the page.

Section cards use the same accents as the screen: Posist gold, audit purple,
staff orange, Famepilot pink, Reelo blue, and calendar teal. Day cells keep a
tier-coloured border. File warnings are not printed.
"""

import logging
from datetime import datetime
from pathlib import Path

logging.getLogger("fontTools").setLevel(logging.ERROR)
logging.getLogger("fpdf").setLevel(logging.ERROR)

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, WrapMode, XPos, YPos

from app.store_health.present import IST, format_ist


_FONT_DIR = Path(__file__).resolve().parent / "fonts"

# Dark enough to read on white paper. Working weekday stays grey.
TIER_PRINT_COLOUR = {
    "Weather caution": (176, 122, 8),
    "Puja / festive": (176, 48, 104),
    "Holiday": (88, 72, 184),
    "Weekend": (12, 112, 156),
    "Working weekday": (139, 148, 158),
}
_NEUTRAL_BORDER = (150, 150, 150)

PAGE_BG = (18, 18, 18)
CARD = (27, 27, 27)
TEXT = (248, 249, 250)
MUTED = (173, 181, 189)
SOFT = (206, 212, 218)
GOLD = (245, 197, 24)
PURPLE = (167, 139, 250)
ORANGE = (251, 146, 60)
PINK = (251, 113, 133)
BLUE = (96, 165, 250)
TEAL = (45, 212, 191)

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
    "active_employees": "Active employees",
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
    "reelo_date_range": "Dates in the Reelo file",
    "reelo_match_status": "Match status",
    "reelo_note": "Note",
}

_CALENDAR_FIGURES = (
    ("Low", "pred_low"),
    ("Mid", "pred_mid"),
    ("High", "pred_high"),
    ("Actual", "actual_net"),
)


class _StorePdf(FPDF):
    def __init__(self, store_label):
        super().__init__(format="A4", unit="mm")
        self.store_label = store_label
        self.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(14, 16, 14)
        self.c_margin = 0
        self.page_background = PAGE_BG

    def header(self):
        if self.page_no() == 1:
            return
        self.set_text_color(*MUTED)
        self.set_font("DejaVu", "", 8)
        self.cell(self.epw - 28, 5, self.store_label)
        self.set_font("DejaVu", "B", 8)
        self.set_text_color(*GOLD)
        self.cell(28, 5, "Store Health", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*GOLD)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y() + 0.4, self.w - self.r_margin, self.get_y() + 0.4)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_text_color(*MUTED)
        self.set_font("DejaVu", "", 8)
        self.cell(0, 8, f"{self.store_label}  ·  {self.page_no()}", align="C")


def render_store_pdf(store, selection, view, insights, context_slots, warnings=None):
    """One store on paper. Insights and city slots stay on the screen page."""
    del selection, insights, context_slots, warnings
    pdf = _StorePdf(store.label)
    pdf.add_page()
    _paragraph(pdf, "Store Health", 20, bold=True, colour=GOLD)
    _paragraph(pdf, store.label, 14, bold=True, colour=TEXT)
    if store.region:
        _paragraph(pdf, store.region, 11, colour=SOFT)
    _paragraph(
        pdf,
        f"Prepared {format_ist(datetime.now(IST))}. A blank is not zero.",
        9,
        colour=MUTED,
    )
    pdf.ln(1)

    _section_box(pdf, "Posist window", _posist_lines(view), GOLD)
    _section_box(pdf, "Menu mix", _menu_lines(view), GOLD)
    _calendar_section(pdf, view)
    _section_box(pdf, "Mystery audit", _audit_lines(view), PURPLE)
    _section_box(pdf, "Keka", _keka_lines(view), ORANGE)
    _section_box(pdf, "Famepilot", _fame_lines(view), PINK)
    _section_box(pdf, "Reelo", _reelo_lines(view), BLUE)

    return bytes(pdf.output())


def _usable_width(pdf):
    return pdf.w - pdf.l_margin - pdf.r_margin


def _text_height(pdf, text, width, size, bold=False):
    pdf.set_font("DejaVu", "B" if bold else "", size)
    return pdf.multi_cell(
        width,
        _line_h(size),
        text,
        dry_run=True,
        output=MethodReturnValue.HEIGHT,
        align="L",
        wrapmode=WrapMode.WORD,
    )


def _line_h(size):
    return max(3.6, size * 0.48)


def _paragraph(pdf, text, size, bold=False, colour=TEXT):
    if not str(text).strip():
        return
    pdf.set_x(pdf.l_margin)
    pdf.set_font("DejaVu", "B" if bold else "", size)
    pdf.set_text_color(*colour)
    pdf.multi_cell(
        0,
        _line_h(size),
        text,
        align="L",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.WORD,
    )
    pdf.ln(0.7)


def _section_box(pdf, title, lines, accent):
    lines = [line for line in lines if str(line).strip()]
    if not lines:
        lines = ["Nothing is on file for this store."]
    width = _usable_width(pdf)
    inner = width - 6
    body = 0
    for line in lines:
        body += _text_height(pdf, line, inner, 10) + 1.1
    block_h = 2.4 + 4 + 6.2 + body + 2
    page_room = pdf.h - pdf.t_margin - pdf.b_margin
    if block_h <= page_room and pdf.get_y() + block_h > pdf.h - pdf.b_margin:
        pdf.add_page()
    if block_h > page_room:
        _paragraph(pdf, title, 13, bold=True, colour=accent)
        for line in lines:
            _paragraph(pdf, line, 10, colour=SOFT)
        pdf.ln(2)
        return
    x = pdf.l_margin
    y = pdf.get_y()
    pdf.set_fill_color(*CARD)
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.4)
    pdf.rect(x, y, width, block_h, style="FD")
    pdf.set_fill_color(*accent)
    pdf.rect(x, y, width, 2.2, style="F")
    pdf.set_auto_page_break(auto=False)
    pdf.set_xy(x + 3, y + 4.2)
    pdf.set_font("DejaVu", "B", 12)
    pdf.set_text_color(*accent)
    pdf.multi_cell(inner, 6, title, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    rule = y + 10.6
    pdf.set_draw_color(*accent)
    pdf.line(x + 3, rule, x + width - 3, rule)
    cursor = rule + 1.6
    for line in lines:
        pdf.set_xy(x + 3, cursor)
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(*SOFT)
        pdf.multi_cell(
            inner,
            _line_h(10),
            line,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            wrapmode=WrapMode.WORD,
        )
        cursor = pdf.get_y() + 1.1
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_y(y + block_h + 3.2)


def _calendar_section(pdf, view):
    lines = []
    if view.get("calendar_share_label"):
        lines.append(view["calendar_share_label"])
    if view.get("calendar_absent_note"):
        lines.append(view["calendar_absent_note"])
    lines.append("Predicted versus actual Net. A blank is not zero.")
    if view.get("posist_actual_days"):
        lines.append(
            "Days without a calendar actual use that day's Posist net. "
            "When Posist net is blank, the day's gross is shown. "
            "Predictions stay blank unless the calendar file has them."
        )
    days = view.get("days") or []
    if not days:
        lines.append("No predicted or actual Net for this store.")
    _section_box(pdf, "Sales calendar", lines, TEAL)
    if days:
        _draw_day_cards(pdf, days)


def _card_lines(day):
    fields = day.get("fields") or {}
    lines = [(f"{day.get('label') or ''}  {day.get('chrome_weekday') or ''}".strip(), 9, True)]
    tier = fields.get("tier") or ""
    if tier:
        lines.append((tier, 8, True))
    for label, key in _CALENDAR_FIGURES:
        value = fields.get(key) or ""
        lines.append((f"{label}   {value}".rstrip(), 8, False))
    driver = fields.get("drivers") or ""
    if driver:
        lines.append((f"Driver   {driver}", 8, False))
    return lines


def _card_height(pdf, day, width):
    inner = width - 7.6
    height = 3.2
    for text, size, bold in _card_lines(day):
        height += _text_height(pdf, text, inner, size, bold=bold) + 0.45
    return height + 1.6


def _draw_day_cards(pdf, days):
    usable = _usable_width(pdf)
    gap = 3.2
    col_w = (usable - gap) / 2
    index = 0
    while index < len(days):
        pair = days[index : index + 2]
        row_h = max(_card_height(pdf, day, col_w) for day in pair)
        if pdf.get_y() + row_h > pdf.h - pdf.b_margin:
            pdf.add_page()
        y = pdf.get_y()
        for column, day in enumerate(pair):
            x = pdf.l_margin + column * (col_w + gap)
            _draw_day_card(pdf, x, y, col_w, row_h, day)
        pdf.set_y(y + row_h + 2.4)
        index += 2


def _draw_day_card(pdf, x, y, width, height, day):
    tier = (day.get("fields") or {}).get("tier") or ""
    colour = TIER_PRINT_COLOUR.get(tier, _NEUTRAL_BORDER)
    pdf.set_auto_page_break(auto=False)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*colour)
    pdf.set_line_width(0.75)
    pdf.rect(x, y, width, height, style="FD")
    pdf.set_fill_color(*colour)
    pdf.rect(x + 1.6, y + 1.8, 3.2, 3.2, style="F")
    cursor = y + 1.5
    inner_x = x + 6.2
    inner_w = width - 7.6
    for text, size, bold in _card_lines(day):
        pdf.set_xy(inner_x, cursor)
        pdf.set_font("DejaVu", "B" if bold else "", size)
        pdf.set_text_color(20, 20, 20)
        pdf.multi_cell(
            inner_w,
            _line_h(size),
            text,
            align="L",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            wrapmode=WrapMode.WORD,
        )
        cursor = pdf.get_y() + 0.45
    pdf.set_auto_page_break(auto=True, margin=16)


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


def _menu_lines(view):
    mix = view.get("menu_mix") or {}
    if not mix.get("has_items"):
        return [mix.get("empty") or "Menu mix is not on file."]
    lines = []
    if mix.get("period_label"):
        lines.append(mix["period_label"])
    for item in mix.get("entries") or []:
        bits = [item.get("item") or ""]
        if item.get("sales"):
            bits.append(item["sales"])
        if item.get("orders"):
            bits.append(f"{item['orders']} orders")
        if item.get("contribution"):
            bits.append(item["contribution"])
        lines.append(" · ".join(bit for bit in bits if bit))
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
        lines.append(f"Window: {posist['window_label']}.")
    if posist.get("days_summed"):
        lines.append(f"Days summed: {posist['days_summed']}.")
    if posist.get("missing_label"):
        lines.append(posist["missing_label"])
    fields = posist.get("fields") or {}
    # Net on the sheet is the gross total when the net column is blank.
    net = fields.get("net") or fields.get("gross") or ""
    bills = fields.get("bills") or ""
    apb = fields.get("apb") or ""
    lines.append(f"Net: {net}" if net else "Net:")
    lines.append(f"Bills: {bills}" if bills else "Bills:")
    # The window figure is summed gross divided by summed bills, not a Posist print.
    lines.append(f"APB, gross divided by bills: {apb}" if apb else "APB, gross divided by bills:")
    return lines


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
        lines.append("Brand aggregate, not this store's score.")
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
    if keka.get("active_state") == "missing":
        lines.append("keka_active.csv is missing.")
    elif keka.get("active_state") == "empty":
        lines.append("keka_active.csv is empty.")
    if keka.get("lead_state") == "missing":
        lines.append("keka.csv is missing.")
    elif keka.get("lead_state") == "empty":
        lines.append("keka.csv is empty.")
    if not keka.get("has_row"):
        lines.append("No Keka row matches this store.")
    else:
        if keka.get("unmatched"):
            lines.append("Unmatched. Not zero.")
        lines.extend(
            _pairs(
                keka.get("fields") or {},
                ["primary_lead", "active_employees", "keka_location", "other_leads", "match_status"],
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
