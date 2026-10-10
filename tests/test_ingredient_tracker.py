import io
import os
import tempfile
import unittest
from datetime import date

# Point at a throwaway database before the app reads its config.
_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_db_file.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _db_file.name

from app import create_app
from app.extensions import db
from app.models import IngredientPrice
from app.routes.ingredient_tracker import build_ingredient_chart_data


def _entry(name, report_date, unit_price, quantity=1, amount=None, row_id=None):
    return IngredientPrice(
        id=row_id,
        ingredient_name=name,
        date=report_date,
        unit_price=unit_price,
        quantity=quantity,
        amount=amount if amount is not None else unit_price * quantity,
        unit='Kg',
        item_code='1',
        discount=0,
        cgst_tax=0,
        sgst_tax=0,
        igst_tax=0,
        non_gst_tax=0,
        total=amount if amount is not None else unit_price * quantity,
    )


class ChartSeriesTests(unittest.TestCase):
    def test_history_stays_in_order_when_newer_and_duplicate_rows_arrive(self):
        entries = [
            _entry('Tomato', date(2025, 6, 13), 40, quantity=10, row_id=5),
            _entry('Tomato', date(2025, 6, 13), 35.46, quantity=8, row_id=162),
            _entry('Tomato', date(2025, 6, 13), 35.46, quantity=8, row_id=304),
            _entry('Tomato', date(2025, 4, 3), 35.46, quantity=8, row_id=400),
            _entry('Tomato', date(2025, 4, 3), 35.46, quantity=8, row_id=401),
            _entry('Tomato', date(2025, 2, 1), 45, quantity=3, row_id=500),
        ]

        ingredient_data, stats, _, _ = build_ingredient_chart_data(entries)
        points = ingredient_data['Tomato']

        self.assertEqual(
            [point['date'] for point in points],
            ['2025-02-01', '2025-04-03', '2025-06-13'],
        )
        self.assertEqual(points[0]['unit_price'], 45)
        self.assertEqual(points[1]['unit_price'], 35.46)
        # Same-day prices are kept as one point instead of snapping back to a duplicate.
        self.assertEqual(points[2]['unit_price'], round((40 + 35.46) / 2, 2))
        self.assertEqual(stats['Tomato']['count'], 3)
        self.assertEqual([point['date'] for point in points], sorted(point['date'] for point in points))


class UploadHistoryTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add(_entry('Tomato', date(2025, 1, 15), 45, quantity=4, amount=180))
            db.session.add(_entry('Onion', date(2025, 2, 2), 30, quantity=6, amount=180))
            db.session.commit()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user'] = {'email': 'ops@dosacoffee.in', 'name': 'Ops User'}

    def _workbook(self, rows):
        import pandas as pd
        frame = pd.DataFrame(
            [['Posist Stock Entry Report'] + [''] * 11, ['Range'] + [''] * 11, [''] * 12] + rows
        )
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, header=False)
        buffer.seek(0)
        return buffer

    def _upload(self, rows, report_date, filename='entry.xlsx'):
        self._login()
        response = self.client.post(
            '/ingredient-tracker/upload',
            data={
                'files': (self._workbook(rows), filename),
                'report_dates': report_date,
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        return response

    def _tomato_points(self):
        self._login()
        page = self.client.get('/ingredient-tracker/')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertNotIn('const ingredientData', html)
        self.assertIn('lazy-skeleton', html)
        response = self.client.get('/ingredient-tracker/data.json')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        return payload['ingredient_data']['Tomato']

    def test_new_report_appends_a_point_and_keeps_stored_values(self):
        self._upload(
            [[141, 'Tomato', 12, 'Kg', 55, 660, 0, 0, 0, 0, 0, 660]],
            '2025-07-01',
        )

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2025-07-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 55])

        with self.app.app_context():
            stored = IngredientPrice.query.filter_by(ingredient_name='Onion').all()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].date, date(2025, 2, 2))
            self.assertEqual(stored[0].unit_price, 30)

    def test_reupload_does_not_reset_or_duplicate_the_series(self):
        rows = [[141, 'Tomato', 12, 'Kg', 55, 660, 0, 0, 0, 0, 0, 660]]
        self._upload(rows, '2025-07-01', filename='july.xlsx')
        self._upload(rows, '2025-07-01', filename='july-again.xlsx')

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2025-07-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 55])

        with self.app.app_context():
            july_rows = IngredientPrice.query.filter_by(
                ingredient_name='Tomato',
                date=date(2025, 7, 1),
            ).count()
            self.assertEqual(july_rows, 1)

    def test_failed_upload_does_not_wipe_existing_points(self):
        self._upload(
            [[141, 'Tomato', 12, 'Kg', 55]],
            '2025-08-01',
            filename='broken.xlsx',
        )
        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15'])
        self.assertEqual(points[0]['unit_price'], 45)

    def _upload_sheet(self, rows, report_date, filename='entry.xlsx'):
        import pandas as pd
        buffer = io.BytesIO()
        pd.DataFrame(rows).to_excel(buffer, index=False, header=False)
        buffer.seek(0)
        self._login()
        response = self.client.post(
            '/ingredient-tracker/upload',
            data={
                'files': (buffer, filename),
                'report_dates': report_date,
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        return response

    def _upload_book(self, sheets, report_date, filename='entry.xlsx'):
        import pandas as pd
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            for name, rows in sheets:
                pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False, header=False)
        buffer.seek(0)
        self._login()
        response = self.client.post(
            '/ingredient-tracker/upload',
            data={
                'files': (buffer, filename),
                'report_dates': report_date,
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        return response

    def test_twelve_column_stock_entry_appends_and_keeps_history(self):
        # Current Posist Stock Entry shape. A 9-column cover sheet makes the
        # old parser assign 12 names and raise "Expected axis has 9 elements,
        # new values have 12 elements" before the entry sheets are read.
        header = [
            'Item Code', 'Item Name', 'Quantity', 'Unit', 'Unit Price',
            'Amount', 'Discount', 'CGST Tax', 'SGST Tax', 'IGST Tax', 'Non GST Tax', 'Total',
        ]
        self._upload_book(
            [
                ('Cover', [
                    ['Kolkata and Delhi warehouse entry reports'] + [''] * 8,
                    ['01-10-2026 to 02-10-2026'] + [''] * 8,
                ]),
                ('Kolkata', [
                    ['Stock Entry Report', '', '', '', '', '', '', '', '', '', '', ''],
                    ['Kolkata Warehouse', '', '', '', '', '', '', '', '', '', '', ''],
                    ['01-10-2026', '', '', '', '', '', '', '', '', '', '', ''],
                    header,
                    [141, 'Tomato', 10, 'Kg', 52, 520, 0, 9, 9, 0, 0, 538],
                ]),
                ('Delhi', [
                    ['Stock Entry Report', '', '', '', '', '', '', '', '', '', '', ''],
                    ['Delhi Warehouse', '', '', '', '', '', '', '', '', '', '', ''],
                    ['02-10-2026', '', '', '', '', '', '', '', '', '', '', ''],
                    header,
                    [10, 'Onion', 4, 'Kg', 28, 112, 0, 1, 1, 0, 0, 114],
                ]),
            ],
            '2026-10-01',
            filename='kolkata-delhi-entry.xlsx',
        )

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2026-10-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 52])

        with self.app.app_context():
            onion = IngredientPrice.query.filter_by(ingredient_name='Onion').order_by(IngredientPrice.date).all()
            self.assertEqual([(row.date, row.unit_price) for row in onion], [
                (date(2025, 2, 2), 30),
                (date(2026, 10, 2), 28),
            ])
            tomato = IngredientPrice.query.filter_by(ingredient_name='Tomato', date=date(2026, 10, 1)).one()
            self.assertEqual(tomato.cgst_tax, 9)
            self.assertEqual(tomato.sgst_tax, 9)
            self.assertEqual(tomato.total, 538)

    def test_nine_column_stock_entry_appends_and_keeps_history(self):
        # A sheet whose own header is a single GST Tax column still loads.
        # Forcing that 9-name list onto the 12-column export is what the upload rejects.
        self._upload_sheet(
            [
                ['Stock Entry Report'] + [''] * 8,
                ['Kolkata Warehouse'] + [''] * 8,
                ['01-10-2026 to 02-10-2026'] + [''] * 8,
                ['Item Code', 'Item Name', 'Quantity', 'Unit', 'Unit Price', 'Amount', 'Discount', 'GST Tax', 'Total'],
                [141, 'Tomato', 10, 'Kg', 52, 520, 0, 18, 538],
                [10, 'Onion', 4, 'Kg', 28, 112, 0, 0, 112],
            ],
            '2026-10-01',
            filename='kolkata-entry.xlsx',
        )

        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2026-10-01'])
        self.assertEqual([point['unit_price'] for point in points], [45, 52])

        with self.app.app_context():
            onion = IngredientPrice.query.filter_by(ingredient_name='Onion').order_by(IngredientPrice.date).all()
            self.assertEqual([(row.date, row.unit_price) for row in onion], [
                (date(2025, 2, 2), 30),
                (date(2026, 10, 1), 28),
            ])
            tomato = IngredientPrice.query.filter_by(ingredient_name='Tomato', date=date(2026, 10, 1)).one()
            self.assertEqual(tomato.gst_tax, 18)

    def test_two_row_consolidated_header_still_loads(self):
        self._upload_sheet(
            [
                ['CONSOLIDATED ENTRY AND SALE REPORT'] + [''] * 11,
                ['Item Code', 'Item Name', 'Quantity', 'Unit', 'Unit Price', 'Amount', 'Discount', 'GST Tax', '', 'IGST Tax', 'Non GST Tax', 'Total'],
                ['', '', '', '', '', '', '', 'CGST Tax', 'SGST Tax', '', '', ''],
                [141, 'Tomato', 6, 'Kg', 48, 288, 0, 5, 5, 0, 0, 298],
            ],
            '2026-10-02',
            filename='consolidated.xlsx',
        )
        points = self._tomato_points()
        self.assertEqual([point['date'] for point in points], ['2025-01-15', '2026-10-02'])
        self.assertEqual(points[-1]['unit_price'], 48)
        with self.app.app_context():
            row = IngredientPrice.query.filter_by(ingredient_name='Tomato', date=date(2026, 10, 2)).one()
            self.assertEqual(row.cgst_tax, 5)
            self.assertEqual(row.sgst_tax, 5)

    def test_entry_report_dates_accumulate_across_days(self):
        header = [
            'Vendor Name', 'Date', 'Transaction Number', 'User Name', 'Invoice Number',
            'Batch Number', 'PR Number', 'PO Number', 'Item Code', 'Item Name', 'Comment',
            'Quantity', 'Unit', 'Unit Price', 'Sub Total', 'Discount', 'Total Tax', 'Total',
        ]
        self._upload_sheet(
            [
                ['Stock Entry Report'] + [''] * 17,
                header,
                ['Delhi Warehouse', '01-10-2026', 1, 'Warehouse', '1', '-', '-', '-', 141, 'Tomato', '-', 8, 'Kg', 60, 480, 0, 0, 480],
                ['Delhi Warehouse', '02-10-2026', 2, 'Warehouse', '2', '-', '-', '-', 141, 'Tomato', '-', 9, 'Kg', 61, 549, 0, 0, 549],
            ],
            '2026-10-01',
            filename='delhi-entry.xlsx',
        )
        points = self._tomato_points()
        self.assertEqual(
            [(point['date'], point['unit_price']) for point in points],
            [('2025-01-15', 45), ('2026-10-01', 60), ('2026-10-02', 61)],
        )

    def test_upload_page_still_links_to_posist(self):
        self._login()
        response = self.client.get('/ingredient-tracker/upload')
        html = response.get_data(as_text=True)
        self.assertIn('https://dosacoffee.posist.biz/eStock/reports/entryReport#', html)
        self.assertIn('Stock Entry Posist Reports', html)


if __name__ == '__main__':
    unittest.main()
