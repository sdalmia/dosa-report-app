import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from flask import jsonify
from app.extensions import db
from app.models import IngredientPrice
from statistics import mean
from app.routes.main import login_required
import os

ingredient_bp = Blueprint('ingredient_tracker', __name__, url_prefix='/ingredient-tracker')

@ingredient_bp.route('/')
@login_required
def dashboard():
    entries = IngredientPrice.query.order_by(IngredientPrice.date.desc()).all()

    # Group price data by ingredient
    from collections import defaultdict
    ingredient_data = defaultdict(list)
    ingredient_stats = {}

    from operator import itemgetter
    # Aggregate total amount per ingredient
    ingredient_totals = defaultdict(float)

    for entry in entries:
        if entry.ingredient_name:
            ingredient_totals[entry.ingredient_name] += entry.amount or 0

    # Get top 20 ingredients by amount
    top_ingredients = sorted(ingredient_totals.items(), key=itemgetter(1), reverse=True)[:20]
    top_ingredient_names = [name for name, _ in top_ingredients]

    def safe_entry(entry):
        return {
            'date': entry.date.strftime('%Y-%m-%d') if entry.date else '',
            'unit_price': entry.unit_price or 0,
            'quantity': entry.quantity or 0,
            'amount': entry.amount or 0,
            'discount': entry.discount or 0,
            'cgst_tax': entry.cgst_tax or 0,
            'sgst_tax': entry.sgst_tax or 0,
            'igst_tax': entry.igst_tax or 0,
            'non_gst_tax': entry.non_gst_tax or 0,
            'total': entry.total or 0,
        }


    for entry in entries:
        if entry.ingredient_name:  # avoid None keys
            ingredient_data[entry.ingredient_name].append(safe_entry(entry))

    all_ingredients = sorted(set(entry.ingredient_name for entry in entries if entry.ingredient_name))

    for name, records in ingredient_data.items():
        prices = [r['unit_price'] for r in records if r['unit_price'] > 0]
        if prices:
            ingredient_stats[name] = {
                'avg': round(mean(prices), 2),
                'high': round(max(prices), 2),
                'low': round(min(prices), 2),
                'count': len(prices)
            }

    return render_template(
        'ingredient_tracker/dashboard.html',
        entries=entries,
        ingredient_data=ingredient_data,
        ingredient_stats=ingredient_stats,
        all_ingredients=all_ingredients,
        top_ingredients=top_ingredient_names
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

                    # Process each row into the DB
                    for _, row in cleaned_df.iterrows():
                        try:
                            # print(row.to_dict())  # This prints each row as a dictionary in one line
                            entry = IngredientPrice(
                                item_code = row['Item Code'],
                                ingredient_name = row['Item Name'],
                                quantity = float(str(row['Quantity']).replace(',', '')),
                                unit = row['Unit'],
                                unit_price = float(str(row['Unit Price']).replace(',', '')),
                                amount = float(str(row['Amount']).replace(',', '')),
                                discount = float(str(row['Discount']).replace(',', '')),
                                cgst_tax = float(str(row['CGST Tax']).replace(',', '')),
                                sgst_tax = float(str(row['SGST Tax']).replace(',', '')),
                                igst_tax = float(str(row['IGST Tax']).replace(',', '')),
                                non_gst_tax = float(str(row['Non GST Tax']).replace(',', '')),
                                total = float(str(row['Total']).replace(',', '')),
                                date = parsed_date
                            )
                            print("successfull Entry :" + str(entry.ingredient_name))
                            db.session.add(entry)
                        except Exception as e:
                            print(f"Error processing row: {e}")

                    db.session.commit()
                    flash("✅ File uploaded successfully!", "success")
                except Exception as e:
                    flash(f"Failed to process file: {e}", 'danger')
                    print(f"File processing error: {e}")

        return redirect(url_for('ingredient_tracker.dashboard'))

    return render_template('ingredient_tracker/upload.html')
