"""Load the newest procurement file of each kind.

The date in the filename decides which file wins. A name with no date is used
only when nothing dated is present, or when it is the only file.
"""

import csv
import os
from pathlib import Path

from app.procurement.numbers import (
    blank,
    dates_in_filename,
    file_rank,
    parse_date,
    parse_number,
    parse_period,
)

# Column groups. Anything not listed stays a string. Blank stays None for numbers.
GRN_NUMERIC = {"qty", "unit_price", "sub_total", "tax", "total"}
GRN_DATES = {"date", "invoice_date"}
CHARGE_NUMERIC = {"amount"}
CHARGE_DATES = {"date"}
RATE_NUMERIC = {
    "lines",
    "qty",
    "sub_total",
    "wavg_rate",
    "min_rate",
    "max_rate",
    "last_rate",
    "item_wavg_all",
    "n_suppliers_for_item",
    "n_cities_for_item",
    "pct_vs_item_wavg_all",
    "pct_vs_cheapest_supplier",
}
RATE_DATES = {"last_date"}
SUMMARY_NUMERIC = {
    "lines",
    "distinct_items",
    "bills",
    "sub_total",
    "tax",
    "total_value",
    "share_of_city_spend_pct",
}
SUMMARY_DATES = {"first_date", "last_date"}
CONSUMPTION_NUMERIC = None  # filled below: every *_amt_* and item_rows
WASTAGE_NUMERIC = {
    "rank_in_store",
    "avg_price",
    "wastage_qty",
    "wastage_amt",
    "yield_wastage_qty",
    "yield_wastage_amt",
    "total_wastage_amt",
    "consumption_qty",
    "consumption_amt",
    "wastage_pct_of_consumption",
}
PO_COVERAGE_NUMERIC = {
    "received_lines",
    "received_bills",
    "received_value",
    "lines_with_po_qty",
    "lines_with_po_number",
    "pct_lines_with_po",
}
PO_COVERAGE_DATES = {"first_date", "last_date"}
PO_SUMMARY_NUMERIC = {
    "pd_lines",
    "pd_purchase_amount",
    "pd_discount",
    "pd_total",
    "grn_lines",
    "grn_total",
    "diff_pd_total_minus_grn",
}
PO_SE_NUMERIC = {
    "pd_lines",
    "pd_purchase_amount",
    "pd_total",
    "grn_lines",
    "grn_total",
    "diff_pd_total_minus_grn",
    "diff_pd_purchase_amount_minus_grn",
}
PO_SE_DATES = {"pd_date", "grn_date"}

ITEM_NUMERIC = {
    "GRN qty",
    "GRN value Rs",
    "Avg GRN rate Rs",
    "WH opening qty",
    "WH to stores qty (indent)",
    "WH to CK qty (issue)",
    "Returned to WH qty",
    "WH net outflow qty",
    "WH outflow value Rs",
    "WH build-up qty (GRN - outflow)",
    "WH closing qty",
    "WH closing value Rs",
    "CK consumed qty",
    "Stores consumed qty",
    "Network consumed qty",
    "Network consumed value Rs",
    "Bought - consumed qty",
    "Bought / consumed (x)",
    "Build-up in days of use",
    "Network closing qty",
    "Network closing days of cover",
    "WH closing days of cover",
    "Wastage qty",
    "Wastage value Rs",
    "Store physical gain/loss Rs",
}

CITY_ORDER = ("Kolkata", "Delhi")
REGION_FOR_CITY = {"Kolkata": "East", "Delhi": "North"}
CITY_FOR_REGION = {"East": "Kolkata", "North": "Delhi"}


def procurement_dir():
    override = os.getenv("PROCUREMENT_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def posist_daily_path():
    override = os.getenv("POSIST_DAILY_CSV")
    if override:
        return Path(override)
    base = os.getenv("STORE_HEALTH_DATA_DIR")
    if base:
        return Path(base) / "posist_daily.csv"
    return Path(__file__).resolve().parents[2] / "data" / "store_health" / "posist_daily.csv"


def _skip_menu_cost_side_file(path):
    """Summary and channel files are not the per-outlet item cost."""
    name = path.name.casefold()
    return "summary" in name or "channel" in name


def menu_item_cost_path(directory):
    return newest_file(directory, "menu_item_cost*.csv", exclude=_skip_menu_cost_side_file)


def recipe_cost_by_item_path(directory):
    return newest_file(directory, "recipe_cost_by_item*.csv")


def preferred_recipe_item_path(directory):
    """Menu item cost supersedes recipe_cost_by_item when both are present."""
    menu = menu_item_cost_path(directory)
    if menu is not None:
        return menu
    return recipe_cost_by_item_path(directory)


def newest_file(directory, pattern, exclude=None):
    """Pick the newest match. Date in the filename wins over mtime."""
    directory = Path(directory)
    if not directory.is_dir():
        return None
    matches = []
    for path in directory.glob(pattern):
        if not path.is_file():
            continue
        if exclude and exclude(path):
            continue
        matches.append(path)
    if not matches:
        return None
    return max(matches, key=file_rank)


def _read_csv(path, numeric, dates=None):
    dates = dates or set()
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        for raw in reader:
            if raw is None:
                continue
            if all(blank(cell) for cell in raw.values()):
                continue
            parsed = {}
            for key, cell in raw.items():
                if key is None:
                    continue
                name = key.strip()
                if name in numeric:
                    parsed[name] = parse_number(cell)
                elif name in dates:
                    parsed[name] = parse_date(cell)
                else:
                    parsed[name] = None if blank(cell) else str(cell).strip()
            rows.append(parsed)
    return rows


def _consumption_numeric_columns(fieldnames):
    numeric = {"item_rows"}
    for name in fieldnames or []:
        if name and ("_amt_" in name or name.endswith("_amt")):
            numeric.add(name)
    return numeric


def _repair_indent_row(row):
    """Merge the unquoted comma in 'Pacific mall, Jasola'."""
    if len(row) == 14 and row[3].endswith("Pacific mall") and row[4].strip().startswith("Jasola"):
        row = row[:3] + [row[3] + "," + row[4]] + row[5:]
    return row


def _read_indent(path):
    """Stock-out lines. The header repeats Subtotal, so this does not use DictReader."""
    rows = []
    warnings = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return rows, warnings
        expected = 13
        for index, raw in enumerate(reader, start=2):
            if not raw or all(blank(cell) for cell in raw):
                continue
            row = _repair_indent_row(list(raw))
            if len(row) != expected:
                if len(warnings) < 8:
                    warnings.append(
                        f"{path.name} row {index} has {len(row)} fields, expected {expected}, so it was skipped."
                    )
                continue
            rows.append(
                {
                    "date": parse_date(row[0]),
                    "store_kitchen": row[1].strip(),
                    "supplier": row[2].strip(),
                    "receiver": row[3].strip(),
                    "item_name": row[4].strip(),
                    "unit": row[5].strip(),
                    "unit_price": parse_number(row[6]),
                    "stock_in_reference": row[7].strip(),
                    "stock_in_qty": parse_number(row[8]),
                    "stock_in_subtotal": parse_number(row[9]),
                    "stock_out_reference": row[10].strip(),
                    "stock_out_qty": parse_number(row[11]),
                    "stock_out_subtotal": parse_number(row[12]),
                    "source": path.name,
                }
            )
    return rows, warnings


def _load_workbook(path, warnings):
    try:
        from openpyxl import load_workbook
    except ImportError:
        warnings.append("openpyxl is not installed, so the consumption workbook was not read.")
        return None
    try:
        book = load_workbook(path, data_only=True, read_only=True)
    except OSError as exc:
        warnings.append(f"{path.name} could not be read ({exc}).")
        return None
    try:
        summary = _summary_metrics(book["summary"]) if "summary" in book.sheetnames else {}
        items = []
        for sheet, city in (("kolkata_items", "Kolkata"), ("delhi_items", "Delhi")):
            if sheet in book.sheetnames:
                items.extend(_sheet_dicts(book[sheet], city, ITEM_NUMERIC))
        flags = _sheet_dicts(book["flags"], None, {"amount_rs"}) if "flags" in book.sheetnames else []
    finally:
        book.close()
    return {"summary": summary, "items": items, "flags": flags, "source": path.name}


def _summary_metrics(worksheet):
    metrics = {}
    for row in worksheet.iter_rows(values_only=True):
        if not row or blank(row[0]):
            continue
        label = str(row[0]).strip()
        if not re_snake(label):
            continue
        kolkata = parse_number(row[1]) if len(row) > 1 else None
        delhi = parse_number(row[2]) if len(row) > 2 else None
        if kolkata is None and delhi is None:
            continue
        metrics[label] = {"Kolkata": kolkata, "Delhi": delhi}
    return metrics


def re_snake(label):
    if not label:
        return False
    for char in label:
        if not (char.islower() or char.isdigit() or char == "_"):
            return False
    return True


def _sheet_dicts(worksheet, city, numeric):
    iterator = worksheet.iter_rows(values_only=True)
    try:
        header_row = next(iterator)
    except StopIteration:
        return []
    header = [str(cell).strip() if cell is not None else "" for cell in header_row]
    rows = []
    for raw in iterator:
        if raw is None or all(blank(cell) for cell in raw):
            continue
        record = {}
        for index, name in enumerate(header):
            if not name:
                continue
            cell = raw[index] if index < len(raw) else None
            if name in numeric:
                record[name] = parse_number(cell)
            else:
                record[name] = None if blank(cell) else str(cell).strip()
        if city:
            record["city"] = city
        rows.append(record)
    return rows


def _posist_rows(path, warnings):
    if not path.exists():
        warnings.append(f"Posist gross file is missing: {path}.")
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "gross" not in reader.fieldnames:
            warnings.append(f"{path.name} has no gross column.")
            return []
        for raw in reader:
            store = (raw.get("store") or "").strip()
            day = parse_date(raw.get("date"))
            if not store or day is None:
                continue
            rows.append(
                {
                    "store": store,
                    "date": day,
                    "gross": parse_number(raw.get("gross")),
                    "net": parse_number(raw.get("net")),
                    "region": (raw.get("region") or "").strip(),
                }
            )
    return rows


def load_procurement(directory=None):
    """Read every procurement feed the pages need. Missing files stay missing."""
    directory = Path(directory) if directory else procurement_dir()
    warnings = []
    files = {
        "grn_lines": newest_file(directory, "grn_lines_warehouses*.csv"),
        "grn_charges": newest_file(directory, "grn_charges_warehouses*.csv"),
        "supplier_rates": newest_file(directory, "supplier_item_rates*.csv"),
        "supplier_summary": newest_file(directory, "supplier_summary*.csv"),
        "consumption": newest_file(directory, "store_consumption_wastage*.csv"),
        "wastage": newest_file(directory, "store_item_wastage_top*.csv"),
        "recipe_items": preferred_recipe_item_path(directory),
        "menu_item_summary": newest_file(directory, "menu_item_cost*summary*.csv"),
        "menu_item_channels": newest_file(directory, "menu_item_cost*channel*.csv"),
        "recipe_lines": newest_file(directory, "recipe_cost_lines*.csv"),
        "recipe_consumption": newest_file(
            directory,
            "recipe_consumption_cost_ideal_plaza*.csv",
            exclude=lambda path: "_lines" in path.name,
        ),
        "recipe_consumption_lines": newest_file(
            directory, "recipe_consumption_cost_ideal_plaza_lines*.csv"
        ),
        "recipe_check": newest_file(directory, "recipe_cost_ideal_plaza_check_vs_consumption*.csv"),
        "po_coverage": newest_file(directory, "po_coverage*.csv"),
        "po_summary": newest_file(directory, "po_vs_grn_reconciliation_summary*.csv"),
        "po_by_se": newest_file(directory, "po_vs_grn_reconciliation_by_se*.csv"),
        "workbook": newest_file(directory, "consumption_vs_purchase_*.xlsx"),
        "indent_kolkata": newest_file(directory, "*Indent*Kolkata*.csv"),
        "indent_delhi": newest_file(directory, "*Indent*Delhi*.csv"),
    }

    grn_lines = _read_csv(files["grn_lines"], GRN_NUMERIC, GRN_DATES) if files["grn_lines"] else []
    grn_charges = _read_csv(files["grn_charges"], CHARGE_NUMERIC, CHARGE_DATES) if files["grn_charges"] else []
    supplier_rates = _read_csv(files["supplier_rates"], RATE_NUMERIC, RATE_DATES) if files["supplier_rates"] else []
    supplier_summary = (
        _read_csv(files["supplier_summary"], SUMMARY_NUMERIC, SUMMARY_DATES) if files["supplier_summary"] else []
    )
    consumption = []
    if files["consumption"]:
        with files["consumption"].open(newline="", encoding="utf-8-sig") as handle:
            fieldnames = csv.DictReader(handle).fieldnames
        consumption = _read_csv(files["consumption"], _consumption_numeric_columns(fieldnames))
    wastage = _read_csv(files["wastage"], WASTAGE_NUMERIC) if files["wastage"] else []
    po_coverage = (
        _read_csv(files["po_coverage"], PO_COVERAGE_NUMERIC, PO_COVERAGE_DATES) if files["po_coverage"] else []
    )
    po_summary = _read_csv(files["po_summary"], PO_SUMMARY_NUMERIC) if files["po_summary"] else []
    po_by_se = _read_csv(files["po_by_se"], PO_SE_NUMERIC, PO_SE_DATES) if files["po_by_se"] else []
    workbook = _load_workbook(files["workbook"], warnings) if files["workbook"] else None

    indent_rows = []
    for key in ("indent_kolkata", "indent_delhi"):
        if not files[key]:
            continue
        parsed, indent_warnings = _read_indent(files[key])
        warnings.extend(indent_warnings)
        indent_rows.extend(parsed)

    posist_path = posist_daily_path()
    posist = _posist_rows(posist_path, warnings)

    period_start, period_end = _period_from_consumption(consumption)
    if period_start is None:
        grn_dates = [row["date"] for row in grn_lines if row.get("date")]
        if grn_dates:
            period_start, period_end = min(grn_dates), max(grn_dates)
    if period_start is None and files["workbook"]:
        start, end = dates_in_filename(files["workbook"].name)
        period_start, period_end = start, end

    return {
        "directory": directory,
        "files": files,
        "warnings": warnings,
        "grn_lines": grn_lines,
        "grn_charges": grn_charges,
        "supplier_rates": supplier_rates,
        "supplier_summary": supplier_summary,
        "consumption": consumption,
        "wastage": wastage,
        "po_coverage": po_coverage,
        "po_summary": po_summary,
        "po_by_se": po_by_se,
        "workbook": workbook,
        "indent_rows": indent_rows,
        "posist": posist,
        "posist_path": posist_path,
        "period_start": period_start,
        "period_end": period_end,
    }


def _period_from_consumption(rows):
    periods = {row.get("period") for row in rows if row.get("period")}
    if len(periods) != 1:
        return None, None
    return parse_period(next(iter(periods)))


def source_name(bundle, key):
    path = bundle["files"].get(key)
    if path is None:
        return ""
    return path.name

