"""PDF and Excel exports for the Wizard.

A4, an 18mm margin, Inter, and an 8pt rhythm. Figures use the rupee sign.
Markdown, file names, and empty sections are left out.
"""

import re
from io import BytesIO
from pathlib import Path

from app.chat.names import indian_digits

_REGULAR = Path("/usr/share/fonts/truetype/macos/Inter-Regular.ttf")
_BOLD = Path("/usr/share/fonts/truetype/macos/Inter-Bold.ttf")
_FILE = re.compile(r"\b[\w./-]+\.(?:csv|xlsx|xls|json|md|py)\b", re.I)
_MARK = re.compile(r"[#*`|]+")
_INK = (31, 26, 23)
_MUTED = (107, 100, 92)
_PAPER = (250, 247, 242)
_BAND = (31, 26, 23)
_ACCENT = (166, 84, 40)
_GREEN = (31, 122, 77)
_RED = (180, 35, 24)
_ZEBRA = (247, 244, 239)
_HEAD = (239, 230, 218)
_LINE = (228, 221, 212)
_MARGIN = 18
_CONTENT = 210 - (2 * _MARGIN)


def plain(text):
    """Reader-facing copy. No markdown and no file names."""
    cleaned = _FILE.sub("", str(text or ""))
    cleaned = _MARK.sub(" ", cleaned)
    cleaned = re.sub(r"\(Rs\)", "", cleaned)
    cleaned = re.sub(r"\bRs\s+", "₹", cleaned)
    cleaned = re.sub(r"(?:\s*[;,]\s*){2,}", "; ", cleaned)
    cleaned = _spoken_dates(cleaned)
    cleaned = cleaned.strip(" ;,")
    return " ".join(cleaned.split())


def _spoken_dates(text):
    months = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    def repl(match):
        month = int(match.group(2))
        day = int(match.group(3))
        if not 1 <= month <= 12:
            return match.group(0)
        return f"{day} {months[month]} {match.group(1)}"

    return re.sub(r"\b(20\d{2})-(\d{2})-(\d{2})\b", repl, text)


def fit_widths(headers, rows, width):
    """Column widths that sum to the content width and follow the text."""
    count = max(len(headers), 1)
    weights = []
    for index in range(count):
        longest = len(str(headers[index] if index < len(headers) else ""))
        for row in rows:
            if index < len(row) and row[index] is not None:
                longest = max(longest, min(len(str(row[index])), 48))
        weights.append(max(longest, 4))
    total = sum(weights) or 1
    widths = [max(16, width * weight / total) for weight in weights]
    scale = width / sum(widths)
    return [item * scale for item in widths]


def rupee(value):
    number = float(value)
    sign = "-" if number < 0 else ""
    amount = abs(number)
    if amount >= 10000000:
        return f"{sign}₹{amount / 10000000:.2f} Cr"
    if amount >= 100000:
        return f"{sign}₹{amount / 100000:.2f} L"
    return f"{sign}₹{indian_digits(amount, 0)}"


def render_pdf(report):
    from fpdf import FPDF

    class Document(FPDF):
        def __init__(self):
            super().__init__(format="A4", unit="mm")
            self.owner_only = bool(report.get("owner_only"))
            if _REGULAR.is_file():
                self.add_font("Body", "", str(_REGULAR))
                self.add_font("Body", "B", str(_BOLD if _BOLD.is_file() else _REGULAR))
                self._face = "Body"
            else:
                self._face = "Helvetica"
            self.set_auto_page_break(auto=True, margin=_MARGIN)
            self.set_margins(_MARGIN, 30, _MARGIN)
            self.alias_nb_pages()

        def header(self):
            self.set_fill_color(*_BAND)
            self.rect(0, 0, 210, 22, "F")
            self.set_text_color(255, 255, 255)
            self.set_xy(_MARGIN, 6)
            self.set_font(self._face, "B", 12)
            self.cell(70, 5, "Dosa Coffee")
            self.set_font(self._face, "", 10)
            self.cell(0, 5, plain(report.get("title") or "Report"), align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_x(_MARGIN)
            self.set_font(self._face, "", 8)
            covered = plain(report.get("coverage") or report.get("sales_through") or "Covered period not loaded")
            when = plain(report.get("generated_at") or "")
            if when.endswith(" IST"):
                when = when[:-4]
            self.set_xy(_MARGIN, 13)
            self.cell(0, 4, f"Covered {covered}"[:120], new_x="LMARGIN", new_y="NEXT")
            self.set_xy(_MARGIN, 17)
            self.cell(0, 4, f"Prepared {when} IST".strip() if when else "")
            self.set_text_color(*_INK)
            self.set_y(28)

        def footer(self):
            self.set_y(-12)
            self.set_font(self._face, "", 8)
            self.set_text_color(*_MUTED)
            tag = "Owner only" if self.owner_only else "Dosa Coffee"
            self.cell(90, 6, tag)
            self.cell(0, 6, f"{self.page_no()} of {{nb}}", align="R")

    pdf = Document()
    pdf.add_page()
    pdf.set_fill_color(*_PAPER)
    _kpis(pdf, report)
    _threats(pdf, report)
    if report.get("chart") and report["chart"].get("series"):
        chart_title = plain(report["chart"].get("title") or "Chart")
        names = {plain(table.get("name") or "") for table in report.get("tables") or []}
        if chart_title in names:
            chart_title = "Largest stores"
        _heading(pdf, chart_title, 13)
        _bars(pdf, report["chart"]["series"])
    for table in report.get("tables") or []:
        rows = [row for row in (table.get("rows") or []) if any(cell not in (None, "") for cell in row)]
        if not rows:
            continue
        _heading(pdf, plain(table.get("name") or "Detail"), 13)
        _table(pdf, table.get("columns") or ["Note"], rows, table.get("numeric_headers"))
        if table.get("footnote"):
            _body(pdf, plain(table["footnote"]), 8)
    steps = [plain(step) for step in (report.get("steps") or []) if plain(step)]
    if steps:
        _heading(pdf, "Next steps", 13)
        for step in steps:
            _body(pdf, step, 10)
    return bytes(pdf.output())


def render_xlsx(report):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    book = Workbook()
    cover = book.active
    cover.title = "Cover"
    rows = [
        ["Dosa Coffee", plain(report.get("title") or "Report")],
        ["Covered", plain(report.get("coverage") or "")],
        ["Prepared", plain(report.get("generated_at") or "")],
        ["Lead", plain(report.get("insight") or "")],
    ]
    for line in report.get("data_lines") or [report.get("sales_through") or ""]:
        rows.append(["Covered", plain(line)])
    if report.get("owner_only"):
        rows.append(["Access", "Owner only"])
    for row in rows:
        cover.append(row)
    cover["A1"].font = Font(name="Calibri", bold=True, size=16, color="FFFFFF")
    cover["A1"].fill = PatternFill("solid", fgColor="1F1A17")
    cover.freeze_panes = "A2"
    cover.column_dimensions["A"].width = 18
    cover.column_dimensions["B"].width = 72
    tables = report.get("tables") or [{"name": "Report", "coverage": report.get("coverage"), "columns": ["Note"], "rows": [["Nothing is loaded."]]}]
    thin = Border(
        left=Side(style="thin", color="E4DDD4"),
        right=Side(style="thin", color="E4DDD4"),
        top=Side(style="thin", color="E4DDD4"),
        bottom=Side(style="thin", color="E4DDD4"),
    )
    header_fill = PatternFill("solid", fgColor="EFE6DA")
    zebra = PatternFill("solid", fgColor="F7F4EF")
    for table in tables:
        sheet = book.create_sheet(_sheet(table.get("name")))
        columns = list(table.get("columns") or ["Note"])
        if "Coverage" not in columns:
            columns.append("Coverage")
        sheet.append([plain(column) for column in columns])
        for cell in sheet[1]:
            cell.font = Font(name="Calibri", bold=True, size=11, color="1F1A17")
            cell.fill = header_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            cell.border = thin
        coverage = plain(table.get("coverage") or "")
        numeric = set(table.get("numeric") or [])
        written_rows = 0
        for raw in table.get("rows") or []:
            if not any(cell not in (None, "") for cell in raw):
                continue
            values = list(raw)
            if len(values) < len(columns) - 1:
                values.extend([None] * (len(columns) - 1 - len(values)))
            values = values[: len(columns) - 1]
            values.append(coverage)
            sheet.append([""] * len(columns))
            written_rows += 1
            excel_row = sheet.max_row
            for index, value in enumerate(values):
                header = columns[index] if index < len(columns) else ""
                cell = sheet.cell(excel_row, index + 1)
                cell.border = thin
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                if written_rows % 2 == 0:
                    cell.fill = zebra
                header_l = header.casefold()
                if index in numeric and isinstance(value, (int, float)) and "percent" in header_l:
                    cell.value = float(value)
                    cell.number_format = "0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif index in numeric and isinstance(value, (int, float)) and "bill" in header_l:
                    cell.value = int(round(value))
                    cell.number_format = "#,##,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif index in numeric and isinstance(value, (int, float)):
                    cell.value = float(value)
                    cell.number_format = '"₹"#,##,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.value = plain(value) if value is not None else ""
        for index in range(1, len(columns) + 1):
            longest = 0
            for row in sheet.iter_rows(min_col=index, max_col=index, max_row=min(sheet.max_row, 40)):
                longest = max(longest, len(str(row[0].value or "")))
            sheet.column_dimensions[get_column_letter(index)].width = min(42, max(12, longest + 2))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.row_dimensions[1].height = 22
    steps = [plain(step) for step in (report.get("steps") or []) if plain(step)]
    if steps:
        sheet = book.create_sheet("Next steps")
        sheet.append(["Step"])
        sheet["A1"].font = Font(name="Calibri", bold=True)
        sheet["A1"].fill = header_fill
        for step in steps:
            sheet.append([step])
        sheet.column_dimensions["A"].width = 88
        sheet.freeze_panes = "A2"
    handle = BytesIO()
    book.save(handle)
    return handle.getvalue()


def _kpis(pdf, report):
    cards = list(report.get("kpis") or [])
    lead = plain(report.get("insight") or "")
    if lead and not cards and lead.casefold() not in {"daily review", "food cost.", "the loaded rows are below."}:
        _body(pdf, lead, 11)
        pdf.ln(1)
    if not cards:
        series = ((report.get("chart") or {}).get("series")) or []
        numbers = []
        for item in series[:4]:
            try:
                numbers.append((item.get("label") or "", float(item.get("value"))))
            except (TypeError, ValueError):
                continue
        changing = any(value < 0 for _label, value in numbers)
        for label, value in numbers:
            tone = "ink"
            if changing and value < 0:
                tone = "red"
            elif changing and value > 0:
                tone = "green"
            cards.append({"label": label, "value": rupee(value) if abs(value) >= 1000 else f"{value:.1f}", "tone": tone})
    if not cards:
        lead = plain(report.get("insight") or "")
        if lead:
            cards = [{"label": "Lead", "value": lead[:42], "tone": "ink"}]
    if not cards:
        return
    gap = 3
    width = (_CONTENT - gap * (len(cards[:4]) - 1)) / max(len(cards[:4]), 1)
    y = pdf.get_y()
    colors = {"red": _RED, "green": _GREEN, "ink": _INK}
    for index, card in enumerate(cards[:4]):
        x = _MARGIN + index * (width + gap)
        pdf.set_fill_color(*_PAPER)
        pdf.set_draw_color(*_LINE)
        pdf.rect(x, y, width, 26, style="FD")
        pdf.set_xy(x + 2, y + 2)
        pdf.set_font(pdf._face, "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(width - 4, 4, plain(card.get("label") or ""), align="L")
        pdf.set_xy(x + 2, y + 7)
        pdf.set_text_color(*colors.get(card.get("tone") or "ink", _INK))
        _fit_cell(pdf, width - 4, 7, plain(str(card.get("value") or "")), 14, bold=True)
        pdf.set_xy(x + 2, y + 15)
        pdf.set_text_color(*colors.get(card.get("tone") or "ink", _INK))
        _fit_cell(pdf, width - 4, 4, plain(str(card.get("delta") or "")), 8, bold=False)
    pdf.set_y(y + 28)
    pdf.set_text_color(*_INK)


def _fit_cell(pdf, width, height, text, size, bold):
    pdf.set_font(pdf._face, "B" if bold else "", size)
    while size > 7 and text and pdf.get_string_width(text) > width:
        size -= 0.5
        pdf.set_font(pdf._face, "B" if bold else "", size)
    pdf.cell(width, height, text, align="L")


def _threats(pdf, report):
    found = []
    for table in report.get("tables") or []:
        for row in table.get("rows") or []:
            text = plain(" ".join(str(cell) for cell in row if cell not in (None, "")))
            lowered = text.casefold()
            if lowered.startswith("behind") or " de-growing" in f" {lowered}" or lowered.startswith("-"):
                found.append(text[:160])
            if len(found) == 3:
                break
    if not found:
        return
    _heading(pdf, "What needs attention", 13)
    for item in found:
        _body(pdf, item, 10)


def _heading(pdf, text, size):
    if pdf.get_y() > 250:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_x(_MARGIN)
    pdf.set_font(pdf._face, "B", size)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(_CONTENT, size * 0.5, text, align="L")
    pdf.ln(1)


def _body(pdf, text, size):
    pdf.set_x(_MARGIN)
    pdf.set_font(pdf._face, "", size)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(_CONTENT, size * 0.5, text, align="L")


def _bars(pdf, series):
    values = []
    for item in series[:5]:
        try:
            values.append((plain(item.get("label") or ""), float(item.get("value") or 0)))
        except (TypeError, ValueError):
            continue
    if not values:
        return
    peak = max(abs(value) for _label, value in values) or 1
    for label, value in values:
        if pdf.get_y() > 265:
            pdf.add_page()
        pdf.set_x(_MARGIN)
        pdf.set_font(pdf._face, "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(46, 6, label[:22])
        tone = _RED if value < 0 else _ACCENT
        pdf.set_fill_color(*tone)
        pdf.rect(pdf.get_x(), pdf.get_y() + 1, max(1.5, abs(value) / peak * 90), 4, style="F")
        pdf.set_xy(pdf.get_x() + 94, pdf.get_y())
        pdf.cell(20, 6, rupee(value) if abs(value) >= 1000 else f"{value:.1f}")
        pdf.ln(7)


def _table(pdf, headers, rows, numeric_headers=None):
    shown = []
    for row in rows:
        shown.append([_cell(header, value) for header, value in zip(headers, list(row) + [""] * len(headers))])
    widths = _measured_widths(pdf, [plain(header) for header in headers], shown)
    numeric = set(numeric_headers or [])
    if not numeric:
        numeric = {index for index, header in enumerate(headers) if _header_is_numeric(header)}
    _header_row(pdf, headers, widths, numeric)
    for index, row in enumerate(shown):
        height = _row_height(pdf, row, widths)
        if pdf.get_y() + height > 275:
            pdf.add_page()
            _header_row(pdf, headers, widths, numeric)
        y = pdf.get_y()
        bold = str(row[0]).casefold() in {"north", "east", "network"}
        pdf.set_fill_color(*(_HEAD if bold else (_ZEBRA if index % 2 else (255, 255, 255))))
        x = _MARGIN
        pdf.rect(x, y, sum(widths), height, style="F")
        for column, (text, width) in enumerate(zip(row, widths)):
            if text.casefold() in {"behind", "ahead", "up", "down"}:
                _chip(pdf, x, y, width, height, text)
                x += width
                continue
            size = 9
            pdf.set_font(pdf._face, "B" if bold else "", size)
            while size > 6.5 and pdf.get_string_width(text or "") > max(width - 2, 4):
                size -= 0.5
                pdf.set_font(pdf._face, "B" if bold else "", size)
            inner = max(width - 2, 4)
            pdf.set_xy(x + 1, y + 1)
            pdf.set_text_color(*_tone(text))
            align = "R" if column in numeric or _numeric(text) else "L"
            if align == "R":
                pdf.cell(inner, max(height - 2, 4.2), text, align="R")
            else:
                try:
                    pdf.multi_cell(inner, 4.2, text, align="L")
                except Exception:
                    pdf.set_xy(x + 1, y + 1)
                    pdf.cell(inner, max(height - 2, 4.2), text[:18], align="L")
            x += width
        pdf.set_y(y + height)


def _measured_widths(pdf, headers, rows):
    """Fit the table. A number column stays wide enough for its whole value."""
    size = 8
    minimums = [8] * max(len(headers), 1)
    while size >= 6:
        pdf.set_font(pdf._face, "", size)
        minimums = []
        for index, header in enumerate(headers):
            texts = [str(header or "")]
            for row in rows:
                if index < len(row) and row[index] not in (None, ""):
                    texts.append(str(row[index]))
            numeric = _header_is_numeric(header)
            if numeric:
                need = max(pdf.get_string_width(text) for text in texts) + 4
            else:
                words = []
                for text in texts:
                    words.extend(text.split() or [text])
                need = max(pdf.get_string_width(word) for word in words) + 4
            minimums.append(max(need, 8))
        if sum(minimums) <= _CONTENT:
            break
        size -= 0.5
    if sum(minimums) > _CONTENT:
        scale = _CONTENT / sum(minimums)
        return [item * scale for item in minimums]
    extra = _CONTENT - sum(minimums)
    text_indexes = [index for index, header in enumerate(headers) if not _header_is_numeric(header)]
    widths = list(minimums)
    if text_indexes and extra:
        share = extra / len(text_indexes)
        for index in text_indexes:
            widths[index] += share
    elif extra and widths:
        widths[0] += extra
    return widths


def _header_is_numeric(header):
    folded = plain(header).casefold()
    return any(token in folded for token in ("gross", "net", "target", "gap", "bill", "apb", "change", "%", "percent", "day"))


def _header_row(pdf, headers, widths, numeric):
    pdf.set_x(_MARGIN)
    pdf.set_fill_color(*_HEAD)
    pdf.set_font(pdf._face, "B", 8)
    pdf.set_text_color(*_INK)
    y = pdf.get_y()
    x = _MARGIN
    pdf.rect(x, y, sum(widths), 8, style="F")
    for index, (header, width) in enumerate(zip(headers, widths)):
        pdf.set_xy(x + 1, y + 1.5)
        pdf.cell(max(width - 2, 4), 5, plain(header), align="R" if index in numeric else "L")
        x += width
    pdf.set_y(y + 8)


def _chip(pdf, x, y, width, height, text):
    tone = _RED if text.casefold() in {"behind", "down"} else _GREEN
    label = text.lower()
    pdf.set_font(pdf._face, "B", 7)
    chip_w = min(width - 2, pdf.get_string_width(label) + 4)
    chip_x = x + width - chip_w - 1
    chip_y = y + max(1, (height - 4.5) / 2)
    pdf.set_fill_color(*tone)
    pdf.rect(chip_x, chip_y, chip_w, 4.5, style="F")
    pdf.set_xy(chip_x, chip_y + 0.4)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(chip_w, 3.6, label, align="C")


def _wrap_count(pdf, text, width):
    """How many lines a cell needs. A long token is allowed to shrink rather than overflow."""
    words = str(text or "").split() or [""]
    usable = max(width - 2, 8)
    pdf.set_font(pdf._face, "", 8)
    lines = 1
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if pdf.get_string_width(trial) <= usable or not current:
            current = trial
        else:
            lines += 1
            current = word
    return lines


def _row_height(pdf, row, widths):
    height = 8
    for text, width in zip(row, widths):
        if not text or _numeric(text):
            continue
        lines = _wrap_count(pdf, text, width)
        height = max(height, 3 + 4.4 * lines)
    return height


def _cell(header, value):
    if value is None:
        return ""
    header_l = str(header or "").casefold()
    if isinstance(value, str):
        return plain(value)
    if "percent" in header_l and isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    if "bill" in header_l and isinstance(value, (int, float)):
        return indian_digits(value, 0)
    if isinstance(value, (int, float)):
        return rupee(value)
    return plain(value)


def _numeric(text):
    token = " ".join((text or "").split())
    if not token or len(token) > 18:
        return False
    return bool(re.fullmatch(r"[+-]?₹?[\d,]+(?:\.\d+)?(?:\s*(?:Cr|L|%))?", token))


def _tone(text):
    token = (text or "").strip()
    if token.startswith("-"):
        return _RED
    if token.startswith("+"):
        return _GREEN
    return _INK


def _sheet(name):
    cleaned = "".join(ch for ch in plain(name or "Sheet") if ch not in "[]:*?/\\")
    return (cleaned or "Sheet")[:31]
