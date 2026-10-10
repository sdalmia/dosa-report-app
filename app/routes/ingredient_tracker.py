import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime, date
from flask import jsonify
from sqlalchemy import func
from app.extensions import db
from app.page_cache import remember
from app.models import IngredientPrice
from statistics import mean
from app.routes.main import login_required
from collections import defaultdict
from operator import itemgetter
import os
import re

ingredient_bp = Blueprint('ingredient_tracker', __name__, url_prefix='/ingredient-tracker')


def _as_float(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError('missing number')
    text = str(value).strip().replace(',', '')
    if text.lower() in {'', 'nan', 'none', '-'}:
        raise ValueError('missing number')
    return float(text)


def _clean_name(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    name = str(value).strip()
    if not name or name.lower() in {'nan', 'none'} or name.lower().startswith('total'):
        return None
    return name


def _dedupe_key(name, report_date, unit_price, quantity, amount):
    iso_date = report_date.isoformat() if hasattr(report_date, 'isoformat') else str(report_date)
    return (
        name,
        iso_date,
        round(float(unit_price or 0), 2),
        round(float(quantity or 0), 2),
        round(float(amount or 0), 2),
    )


# Current Posist Stock Entry sheets use this 12-column header. A leading
# sheet in the same workbook can be narrower; assigning these 12 names to
# that sheet raises "Length mismatch: Expected axis has 9 elements, new
# values have 12 elements" and the entry sheets never get read.
_LEGACY_12_COLUMNS = [
    'Item Code', 'Item Name', 'Quantity', 'Unit', 'Unit Price',
    'Amount', 'Discount', 'CGST Tax', 'SGST Tax',
    'IGST Tax', 'Non GST Tax', 'Total',
]
_COLUMN_ALIASES = (
    ('item_code', ('item code',)),
    ('ingredient_name', ('item name',)),
    ('quantity', ('quantity', 'qty')),
    ('unit', ('unit', 'uom')),
    ('unit_price', ('unit price', 'price', 'rate', 'unit rate')),
    ('amount', ('amount', 'sub total', 'subtotal', 'taxable value', 'taxable amount')),
    ('discount', ('discount',)),
    ('cgst_tax', ('cgst tax', 'cgst')),
    ('sgst_tax', ('sgst tax', 'sgst')),
    ('igst_tax', ('igst tax', 'igst')),
    ('non_gst_tax', ('non gst tax', 'non-gst tax', 'non gst')),
    ('gst_tax', ('gst tax', 'total tax', 'tax')),
    ('total', ('total',)),
    ('line_date', ('date', 'entry date', 'transaction date')),
)
_SUBHEADER_LABELS = {'cgst tax', 'sgst tax', 'igst tax', 'non gst tax', 'cgst', 'sgst', 'igst'}


def _cell_text(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    return str(value).strip()


def _norm_label(value):
    text = _cell_text(value).lower().replace('_', ' ').replace('-', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def _unique_headers(names):
    seen = {}
    unique = []
    for index, name in enumerate(names):
        label = name or f'column_{index}'
        if label in seen:
            seen[label] += 1
            unique.append(f'{label}_{seen[label]}')
        else:
            seen[label] = 0
            unique.append(label)
    return unique


def _named_table(raw_df, names, data_start):
    """Align the body to the header width without dropping columns.

    Empty tax columns are part of the 12-column Stock Entry layout. Dropping
    them leaves 9 columns, and writing the 12 header names back raises
    "Length mismatch: Expected axis has 9 elements, new values have 12 elements".
    """
    body = raw_df.iloc[data_start:].copy()
    width = max(len(names), body.shape[1])
    names = list(names) + [''] * (width - len(names))
    if body.shape[1] < width:
        for index in range(body.shape[1], width):
            body[index] = None
    body = body.iloc[:, :width]
    body.columns = _unique_headers(names[:width])
    return body.reset_index(drop=True)


def _header_index(raw_df):
    for idx in range(len(raw_df)):
        labels = [_norm_label(value) for value in raw_df.iloc[idx].tolist()]
        if 'item name' in labels and ('quantity' in labels or 'qty' in labels or 'item code' in labels):
            return idx
    return None


def _stock_entry_table(raw_df):
    """Read the sheet's own header instead of forcing a 9-column layout.

    The current Stock Entry export is 12 columns: Item Code, Item Name,
    Quantity, Unit, Unit Price, Amount, Discount, then the tax columns and
    Total. Consolidated workbooks put CGST Tax and SGST Tax on the next row
    under a merged GST Tax cell; that blank cell still counts as a column.
    """
    header_idx = _header_index(raw_df)
    if header_idx is None:
        if raw_df.shape[1] == 12:
            return _named_table(raw_df, _LEGACY_12_COLUMNS, 0)
        raise ValueError(
            f'Unrecognized Posist export ({raw_df.shape[1]} columns) '
            'and no Item Name header was found.'
        )

    names = [_cell_text(value) for value in raw_df.iloc[header_idx].tolist()]
    data_start = header_idx + 1
    if data_start < len(raw_df):
        child_labels = [_norm_label(value) for value in raw_df.iloc[data_start].tolist()]
        if any(label in _SUBHEADER_LABELS for label in child_labels):
            child_names = [_cell_text(value) for value in raw_df.iloc[data_start].tolist()]
            width = max(len(names), len(child_names))
            names = names + [''] * (width - len(names))
            child_names = child_names + [''] * (width - len(child_names))
            names = [child or parent for parent, child in zip(names, child_names)]
            data_start += 1
    return _named_table(raw_df, names, data_start)


def _map_columns(columns):
    normalized = [(column, _norm_label(column)) for column in columns]
    used = set()
    mapping = {}
    for field, aliases in _COLUMN_ALIASES:
        for alias in aliases:
            for column, label in normalized:
                if column in used or label != alias:
                    continue
                mapping[field] = column
                used.add(column)
                break
            if field in mapping:
                break
    return mapping


def _optional_number(row, columns, field):
    column = columns.get(field)
    if column is None:
        return 0.0
    value = row[column]
    if value is None or (isinstance(value, float) and pd.isna(value)) or _cell_text(value) == '':
        return 0.0
    return _as_float(value)


def _parse_report_date(value, fallback):
    if value is None or (isinstance(value, float) and pd.isna(value)) or _cell_text(value) == '':
        return fallback
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, dayfirst=True, errors='coerce')
    if pd.isna(parsed):
        return fallback
    return parsed.date()


_DATE_IN_TEXT = re.compile(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b')


def _dates_in_value(value):
    if isinstance(value, datetime):
        return [value.date()]
    if isinstance(value, date):
        return [value]
    found = []
    for day, month, year in _DATE_IN_TEXT.findall(_cell_text(value)):
        full_year = int(year) + (2000 if len(year) == 2 else 0)
        try:
            found.append(date(full_year, int(month), int(day)))
        except ValueError:
            continue
    return found


def _sheet_fallback_date(raw_df, fallback_date):
    """Use a single date printed above the header, such as a warehouse sheet dated 01-10-2026."""
    header_idx = _header_index(raw_df)
    if header_idx is None:
        return fallback_date
    found = []
    for idx in range(header_idx):
        for value in raw_df.iloc[idx].tolist():
            found.extend(_dates_in_value(value))
    unique = list(dict.fromkeys(found))
    if len(unique) == 1:
        return unique[0]
    return fallback_date


def extract_stock_entries(raw_df, fallback_date):
    sheet_date = _sheet_fallback_date(raw_df, fallback_date)
    table = _stock_entry_table(raw_df)
    columns = _map_columns(list(table.columns))
    if 'ingredient_name' not in columns or 'unit_price' not in columns:
        raise ValueError('Posist export is missing Item Name or Unit Price.')

    entries = []
    for _, row in table.iterrows():
        ingredient_name = _clean_name(row[columns['ingredient_name']])
        if not ingredient_name:
            continue
        try:
            unit_price = _as_float(row[columns['unit_price']])
        except ValueError:
            continue
        if unit_price <= 0:
            continue
        quantity = _optional_number(row, columns, 'quantity')
        amount = _optional_number(row, columns, 'amount')
        if amount == 0 and quantity:
            amount = round(unit_price * quantity, 2)
        item_code = row[columns['item_code']] if 'item_code' in columns else None
        if item_code is None or (isinstance(item_code, float) and pd.isna(item_code)):
            item_code = None
        else:
            item_code = _cell_text(item_code)
        unit = row[columns['unit']] if 'unit' in columns else None
        if unit is None or (isinstance(unit, float) and pd.isna(unit)) or _cell_text(unit) == '':
            unit = None
        else:
            unit = _cell_text(unit)
        entries.append({
            'item_code': item_code,
            'ingredient_name': ingredient_name,
            'quantity': quantity,
            'unit': unit,
            'unit_price': unit_price,
            'amount': amount,
            'discount': _optional_number(row, columns, 'discount'),
            'cgst_tax': _optional_number(row, columns, 'cgst_tax'),
            'sgst_tax': _optional_number(row, columns, 'sgst_tax'),
            'igst_tax': _optional_number(row, columns, 'igst_tax'),
            'non_gst_tax': _optional_number(row, columns, 'non_gst_tax'),
            'gst_tax': _optional_number(row, columns, 'gst_tax'),
            'total': _optional_number(row, columns, 'total'),
            'date': _parse_report_date(row[columns['line_date']], sheet_date) if 'line_date' in columns else sheet_date,
        })
    return entries


def extract_workbook(source, fallback_date):
    """Parse every sheet. A narrow cover sheet is not the stock entry table.

    Kolkata and Delhi warehouse reports are often separate sheets in one
    workbook, each with the 12-column Item Name header. The first sheet can
    be a 9-column cover; that is what makes a fixed 12-name assignment raise
    the length mismatch before the entry sheets are read.
    """
    sheets = pd.read_excel(source, header=None, sheet_name=None)
    frames = list(sheets.values()) if isinstance(sheets, dict) else [sheets]
    records = []
    header_error = None
    for frame in frames:
        if frame is None or frame.empty:
            continue
        try:
            records.extend(extract_stock_entries(frame, fallback_date))
        except ValueError as exc:
            if 'no Item Name header' in str(exc):
                continue
            header_error = exc
    if records:
        return records
    if header_error:
        raise header_error
    raise ValueError('No ingredient rows were found in this file.')


def build_ingredient_chart_data(entries):
    """One chronological point per ingredient per day, without dropping older days.

    Repeat uploads of the same Posist row are ignored. Different prices on the
    same day become a single point so the line does not snap back to an older
    duplicate. Other dates are left in place, newest date last.
    """
    unique_rows = defaultdict(list)
    seen = defaultdict(set)
    totals = defaultdict(float)

    for entry in entries:
        name = _clean_name(entry.ingredient_name)
        price = entry.unit_price or 0
        if not name or not entry.date or price <= 0:
            continue
        key = _dedupe_key(name, entry.date, price, entry.quantity, entry.amount)
        if key in seen[name]:
            continue
        seen[name].add(key)
        unique_rows[name].append(entry)
        totals[name] += entry.amount or 0

    ingredient_data = {}
    ingredient_stats = {}

    for name, rows in unique_rows.items():
        by_date = defaultdict(list)
        for row in rows:
            by_date[row.date].append(row)

        points = []
        for report_date in sorted(by_date):
            day_rows = by_date[report_date]
            distinct_prices = []
            seen_prices = set()
            for row in day_rows:
                rounded = round(row.unit_price, 2)
                if rounded in seen_prices:
                    continue
                seen_prices.add(rounded)
                distinct_prices.append(rounded)
            points.append({
                'date': report_date.strftime('%Y-%m-%d'),
                'unit_price': round(mean(distinct_prices), 2),
                'quantity': round(sum((row.quantity or 0) for row in day_rows), 2),
                'amount': round(sum((row.amount or 0) for row in day_rows), 2),
                'discount': round(sum((row.discount or 0) for row in day_rows), 2),
                'cgst_tax': round(sum((row.cgst_tax or 0) for row in day_rows), 2),
                'sgst_tax': round(sum((row.sgst_tax or 0) for row in day_rows), 2),
                'igst_tax': round(sum((row.igst_tax or 0) for row in day_rows), 2),
                'non_gst_tax': round(sum((row.non_gst_tax or 0) for row in day_rows), 2),
                'total': round(sum((row.total or 0) for row in day_rows), 2),
            })

        ingredient_data[name] = points
        series_prices = [point['unit_price'] for point in points]
        ingredient_stats[name] = {
            'avg': round(mean(series_prices), 2),
            'high': round(max(series_prices), 2),
            'low': round(min(series_prices), 2),
            'count': len(series_prices),
        }

    top_ingredients = [
        name for name, _ in sorted(totals.items(), key=itemgetter(1), reverse=True)[:20]
    ]
    all_ingredients = sorted(ingredient_data)
    return ingredient_data, ingredient_stats, all_ingredients, top_ingredients


def ingredient_bundle():
    """Chart series, cached until a price row is added or removed."""
    count, max_id, price_sum, newest = db.session.query(
        func.count(IngredientPrice.id),
        func.max(IngredientPrice.id),
        func.coalesce(func.sum(IngredientPrice.unit_price), 0),
        func.max(IngredientPrice.date),
    ).one()
    token = (count or 0, max_id or 0, round(float(price_sum or 0), 2), str(newest or ""))

    def build():
        entries = IngredientPrice.query.order_by(
            IngredientPrice.date.asc(),
            IngredientPrice.id.asc(),
        ).all()
        ingredient_data, ingredient_stats, all_ingredients, top_ingredients = build_ingredient_chart_data(entries)
        return {
            "ingredient_data": ingredient_data,
            "ingredient_stats": ingredient_stats,
            "all_ingredients": all_ingredients,
            "top_ingredients": top_ingredients,
        }

    return remember(("ingredient-charts", token), build)


@ingredient_bp.route('/')
@login_required
def dashboard():
    bundle = ingredient_bundle()
    return render_template(
        'ingredient_tracker/dashboard.html',
        top_ingredients=bundle["top_ingredients"],
    )


@ingredient_bp.route('/data.json')
@login_required
def chart_data():
    response = jsonify(ingredient_bundle())
    response.headers["Cache-Control"] = "private, max-age=60"
    return response


@ingredient_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':

        files = request.files.getlist('files')
        dates = request.form.getlist('report_dates')

        if len(files) != len(dates):
            flash('Each file must have a corresponding report date.', 'danger')
            return redirect(url_for('ingredient_tracker.upload'))

        for i, file in enumerate(files):
            
            if file.filename.endswith('.xlsx'):

                print("Opening the file...")

                try:

                    # Read every sheet and use its Item Name header. Do not force a
                    # 9-column layout onto the 12-column Stock Entry export.
                    parsed_date = datetime.strptime(dates[i], '%Y-%m-%d').date()
                    records = extract_workbook(file, parsed_date)
                    print("Parsed ingredient rows:", len(records))

                    # Keep previously stored dates. Only skip a row when this exact
                    # observation was already saved, so a new report extends history.
                    dates_in_file = {record['date'] for record in records}
                    existing_keys = set()
                    if dates_in_file:
                        existing_keys = {
                            _dedupe_key(row.ingredient_name, row.date, row.unit_price, row.quantity, row.amount)
                            for row in IngredientPrice.query.filter(IngredientPrice.date.in_(dates_in_file)).all()
                            if row.ingredient_name and row.date
                        }

                    if not records:
                        raise ValueError('No ingredient rows were found in this file.')

                    for record in records:
                        key = _dedupe_key(
                            record['ingredient_name'],
                            record['date'],
                            record['unit_price'],
                            record['quantity'],
                            record['amount'],
                        )
                        if key in existing_keys:
                            continue
                        print("successfull Entry :" + str(record['ingredient_name']))
                        db.session.add(IngredientPrice(**record))
                        existing_keys.add(key)

                    db.session.commit()
                    flash("✅ File uploaded successfully!", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Failed to process file: {e}", 'danger')
                    print(f"File processing error: {e}")

        return redirect(url_for('ingredient_tracker.dashboard'))

    return render_template('ingredient_tracker/upload.html')
