import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from flask import jsonify
from app.extensions import db
from app.models import IngredientPrice
from statistics import mean
from app.routes.main import login_required
from collections import defaultdict
from operator import itemgetter
import os

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


@ingredient_bp.route('/')
@login_required
def dashboard():
    entries = IngredientPrice.query.order_by(
        IngredientPrice.date.asc(),
        IngredientPrice.id.asc(),
    ).all()
    ingredient_data, ingredient_stats, all_ingredients, top_ingredients = build_ingredient_chart_data(entries)

    return render_template(
        'ingredient_tracker/dashboard.html',
        entries=entries,
        ingredient_data=ingredient_data,
        ingredient_stats=ingredient_stats,
        all_ingredients=all_ingredients,
        top_ingredients=top_ingredients
    )


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

                    # Read the file without assuming a header
                    raw_df = pd.read_excel(file, header=None) 

                    print("Dropping the first 3 rows from " + file.filename)
                    cleaned_df = raw_df.iloc[3:].reset_index(drop=True)

                    # Inspect column count
                    print("Number of columns in cleaned_df:", cleaned_df.shape[1])
                    print("First row preview:", cleaned_df.iloc[0].tolist())

                    # Set custom column headers
                    cleaned_df.columns = [
                        'Item Code', 'Item Name', 'Quantity', 'Unit', 'Unit Price',
                        'Amount', 'Discount', 'CGST Tax', 'SGST Tax',
                        'IGST Tax', 'Non GST Tax', 'Total'
                    ]

                    parsed_date = datetime.strptime(dates[i], '%Y-%m-%d').date()
                    # First row preview: [280, 'Raw Pumpkin', 531600, 'Kg', '27.00', '14,353.20', '0.00', '0.00', '0.00', '0.00', '0.00', '14,353.20']

                    # print("Cleaned columns:", cleaned_df.columns.tolist())

                    # Keep previously stored dates. Only skip a row when this exact
                    # observation was already saved, so a new report extends history.
                    existing_keys = {
                        _dedupe_key(row.ingredient_name, row.date, row.unit_price, row.quantity, row.amount)
                        for row in IngredientPrice.query.filter(IngredientPrice.date == parsed_date).all()
                        if row.ingredient_name and row.date
                    }

                    # Process each row into the DB
                    for _, row in cleaned_df.iterrows():
                        try:
                            ingredient_name = _clean_name(row['Item Name'])
                            if not ingredient_name:
                                continue
                            quantity = _as_float(row['Quantity'])
                            unit_price = _as_float(row['Unit Price'])
                            amount = _as_float(row['Amount'])
                            if unit_price <= 0:
                                continue
                            key = _dedupe_key(ingredient_name, parsed_date, unit_price, quantity, amount)
                            if key in existing_keys:
                                continue
                            # print(row.to_dict())  # This prints each row as a dictionary in one line
                            entry = IngredientPrice(
                                item_code = row['Item Code'],
                                ingredient_name = ingredient_name,
                                quantity = quantity,
                                unit = None if pd.isna(row['Unit']) else row['Unit'],
                                unit_price = unit_price,
                                amount = amount,
                                discount = _as_float(row['Discount']),
                                cgst_tax = _as_float(row['CGST Tax']),
                                sgst_tax = _as_float(row['SGST Tax']),
                                igst_tax = _as_float(row['IGST Tax']),
                                non_gst_tax = _as_float(row['Non GST Tax']),
                                total = _as_float(row['Total']),
                                date = parsed_date
                            )
                            print("successfull Entry :" + str(entry.ingredient_name))
                            db.session.add(entry)
                            existing_keys.add(key)
                        except Exception as e:
                            print(f"Error processing row: {e}")

                    db.session.commit()
                    flash("✅ File uploaded successfully!", "success")
                except Exception as e:
                    db.session.rollback()
                    flash(f"Failed to process file: {e}", 'danger')
                    print(f"File processing error: {e}")

        return redirect(url_for('ingredient_tracker.dashboard'))

    return render_template('ingredient_tracker/upload.html')
